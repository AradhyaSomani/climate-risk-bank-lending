"""Phase 1G: EM-DAT India flood and storm records, geocoded to Census 2011 districts.

Input: the EM-DAT public table exported as xlsx (or csv) from public.emdat.be after free
registration, saved under data/raw/emdat/. EM-DAT's terms forbid redistributing the raw
file, so it is never committed and only derived counts and flags are published.

Kept: floods (every subtype, plus glacial lake outburst floods) and tropical cyclones.
Other storms (thunderstorms, lightning, hail, dust storms, "severe weather") are dropped:
EM-DAT files them under Storm, but they are not cyclones.

Location comes from the `GADM Admin Units` column (JSON, keys gid_1/name_1 and
gid_2/name_2), falling back to the deprecated `Admin Units` column (adm1_name/adm2_name)
and finally to the free-text `Location`. A GADM district's state is read from its gid
(IND.5.15_1 lies in IND.5_1), with the gid-to-state map taken from the export itself.
District names are matched within their state, then within the record's states, then across
India; names of districts created or renamed after 2011 are mapped to their Census 2011
district through configs/district_aliases.yaml. States the units leave out but the
`Location` text names are added. Records that only name a state are kept with geo_level =
"state", records with no usable place with geo_level = "country"; `record_level` is the
finest level a record reaches, so record_level = "state" flags a record with no district.
Non-exact matches go to data/interim/emdat_geocode_review.csv for a manual check.

    python -m cri.ingest.emdat data/raw/emdat/emdat_india.xlsx
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from cri import config
from cri.geo.districts import load_districts
from cri.geo.names import best_match, normalise

log = logging.getLogger(__name__)

OUT_NAME = "disaster_records.parquet"
TYPES = {"Flood": "flood", "Glacial lake outburst flood": "flood", "Storm": "cyclone"}
CYCLONE_SUBTYPES = {"Tropical cyclone"}
ALIASES = config.REPO_ROOT / "configs" / "district_aliases.yaml"
PLACE_WORDS = (r"\b(districts?|provinces?|states?|union territor(y|ies)|towns?|city|cities|"
               r"villages?|areas?|regions?|blocks?|talukas?|tehsils?|parts? of|near|western|"
               r"eastern|northern|southern|central|coastal)\b")
NUMERIC = {
    "Total Deaths": "total_deaths",
    "Total Affected": "total_affected",
    "Total Damage ('000 US$)": "total_damage_kusd",
    "Total Damage, Adjusted ('000 US$)": "total_damage_adj_kusd",
}


def read_export(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path) if path.suffix in {".xlsx", ".xls"} else pd.read_csv(path)
    # EM-DAT uses a typographic apostrophe in the money columns; normalise it
    df.columns = [c.replace("‘", "'").replace("’", "'").strip() for c in df.columns]
    df = df[(df["ISO"] == "IND") & df["Disaster Type"].isin(list(TYPES))].copy()
    storm = df["Disaster Type"] == "Storm"
    other = storm & ~df["Disaster Subtype"].isin(CYCLONE_SUBTYPES)
    if other.any():
        log.info("dropped %d storms that are not tropical cyclones (%s)", int(other.sum()),
                 ", ".join(sorted(df.loc[other, "Disaster Subtype"].dropna().unique())))
    return df[~other].reset_index(drop=True)


def _date(y, m, d, end: bool) -> tuple[pd.Timestamp | None, str]:
    if pd.isna(y):
        return None, "missing"
    y = int(y)
    if pd.isna(m):
        return pd.Timestamp(y, 12, 31) if end else pd.Timestamp(y, 1, 1), "year"
    m = int(m)
    if pd.isna(d):
        first = pd.Timestamp(y, m, 1)
        return (first + pd.offsets.MonthEnd(0)) if end else first, "month"
    return pd.Timestamp(y, m, int(d)), "day"


def _gid_parent(gid2: str) -> str:
    return re.sub(r"^(\w+\.\d+)\.\d+(_\d+)$", r"\1\2", gid2)  # IND.5.15_1 -> IND.5_1


def gid_states(df: pd.DataFrame, all_districts: dict[str, object] | None = None,
               id_state: dict | None = None) -> dict[str, str]:
    """GADM gid_1 -> state name, from every state-level unit in the export. A gid_1 that
    never appears as a state (GADM files Indian Kashmir under Z01.14_1) takes the state
    that most of its district names belong to, when `all_districts` is given."""
    out, children = {}, {}
    for raw in df.get("GADM Admin Units", pd.Series(dtype=object)).dropna():
        if isinstance(raw, str) and raw.strip().startswith("["):
            for u in json.loads(raw):
                if "gid_1" in u and "name_1" in u:
                    out[u["gid_1"]] = u["name_1"]
                elif isinstance(u.get("gid_2"), str) and "name_2" in u:
                    children.setdefault(_gid_parent(u["gid_2"]), set()).add(u["name_2"])
    if all_districts is None or id_state is None:
        return out
    for gid, names in children.items():
        if gid in out:
            continue
        votes = pd.Series([id_state[all_districts[normalise(n)]] for n in names
                           if normalise(n) in all_districts])
        if len(votes) and votes.value_counts().iloc[0] > len(names) / 2:
            out[gid] = votes.value_counts().index[0]
    return out


def admin_units(row: pd.Series, gid1: dict[str, str] | None = None
                ) -> tuple[list[str], list[tuple[str, str | None]]]:
    """(state names, [(district name, its state or None)]) from the admin-unit JSON."""
    gid1 = gid1 or {}
    for col, k1, k2 in (("GADM Admin Units", "name_1", "name_2"),
                        ("Admin Units", "adm1_name", "adm2_name")):
        raw = row.get(col)
        if isinstance(raw, str) and raw.strip().startswith("["):
            units = json.loads(raw)
            states = {u[k1] for u in units if k1 in u}
            districts = []
            for u in units:
                if k2 not in u:
                    continue
                st = u.get(k1)
                if st is None and isinstance(u.get("gid_2"), str):
                    st = gid1.get(_gid_parent(u["gid_2"]))
                districts.append((u[k2], st))
            return sorted(states), sorted(set(districts), key=lambda d: (d[0], d[1] or ""))
    return [], []


def _clean_place(text: str) -> list[str]:
    """Place names in one piece of free text, with words like 'districts' removed."""
    text = re.sub(PLACE_WORDS, " ", text, flags=re.IGNORECASE)
    names = re.split(r"\band\b|&|/", text)
    return [n.strip(" .-'\"") for n in names if len(n.strip(" .-'\"")) > 2]


def parse_location(text: str, states: dict[str, str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Free-text `Location`, e.g. "Puri, Khordha districts (Orissa province), Kolkata (West
    Bengal)": a state in brackets applies to every name since the previous bracket.
    `states` maps each normalised state name (and later state, e.g. telangana) to the key
    that is returned for it."""
    def state_in(piece: str) -> str | None:
        key = normalise(re.sub(PLACE_WORDS, " ", piece, flags=re.IGNORECASE))
        if key in states:
            return key
        return next((k for k in states if re.search(rf"\b{re.escape(k)}\b", key)), None)

    segments, depth, cur = [], 0, ""
    for ch in text:  # split on commas and semicolons outside brackets
        depth += (ch == "(") - (ch == ")")
        if ch in ",;" and depth == 0:
            segments.append(cur)
            cur = ""
        else:
            cur += ch
    segments.append(cur)

    found_states, districts, pending = [], [], []
    for seg in (x.strip() for x in segments if x.strip()):
        m = re.match(r"^(.*?)\((.*)\)\s*$", seg)
        if not m:
            pending.append(seg)
            continue
        inner = [x for x in re.split(r"[,;]", m.group(2)) if x.strip()]
        st = next((k for k in (state_in(x) for x in inner) if k), None)
        pending.append(m.group(1))
        if st is None:
            pending += inner
            continue
        found_states.append(states[st])
        pending += [x for x in inner if state_in(x) is None]
        districts += [(n, states[st]) for piece in pending for n in _clean_place(piece)]
        pending = []
    for piece in pending:
        st = state_in(piece)
        if st and normalise(re.sub(PLACE_WORDS, " ", piece, flags=re.IGNORECASE)) == st:
            found_states.append(states[st])
        else:
            districts += [(n, None) for n in _clean_place(piece)]
    return found_states, districts


def load_aliases(path: Path = ALIASES) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """({normalised later state: Census 2011 state}, {normalised Census 2011 state:
    {normalised later district name: Census 2011 district name}})."""
    if not path.exists():
        return {}, {}
    raw = yaml.safe_load(path.read_text()) or {}
    states = {normalise(a): st for a, st in (raw.get("states") or {}).items()}
    districts = {normalise(st): {normalise(a): name for a, name in m.items()}
                 for st, m in (raw.get("districts") or {}).items()}
    return states, districts


def geocode(df: pd.DataFrame, districts: pd.DataFrame,
            aliases: tuple[dict[str, str], dict[str, dict[str, str]]] | None = None
            ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long table: one row per record and district (or per record and state)."""
    state_alias, aliases = load_aliases() if aliases is None else aliases
    states = {normalise(s): s for s in districts.state.unique()}
    by_state = {
        normalise(s): {normalise(n): i for n, i in zip(g.name, g.district_id, strict=True)}
        for s, g in districts.groupby("state")
    }
    all_d = {normalise(n): i for n, i in zip(districts.name, districts.district_id, strict=True)}
    id_state = dict(zip(districts.district_id, districts.state, strict=True))
    gid1 = gid_states(df, all_d, id_state)
    lookup = {k: k for k in states} | {
        a: normalise(st) for a, st in state_alias.items() if normalise(st) in states}

    def state_key(name) -> str | None:
        if not name:
            return None
        name = state_alias.get(normalise(name), name)  # Telangana -> Andhra Pradesh
        hit = best_match(name, {k: k for k in states})
        return hit[0] if hit else None

    def match(name: str, own: str | None, listed: list[str]):
        """(district_id, method, score) or None: own state, listed states, then India."""
        key = normalise(name)
        for sk in [own] if own else listed:
            if sk and key in aliases.get(sk, {}):
                return by_state[sk][normalise(aliases[sk][key])], "alias", 1.0
        pools = [by_state.get(own, {})] if own else []
        pools.append({k: v for sk in listed for k, v in by_state.get(sk, {}).items()})
        for pool in pools:
            if pool and (hit := best_match(name, pool)):
                return hit
        for sk, m in aliases.items():  # an alias whose state was not given
            if key in m:
                return by_state[sk][normalise(m[key])], "alias_national", 1.0
        hit = best_match(name, all_d, cutoff=0.92)
        return (hit[0], f"{hit[1]}_national", hit[2]) if hit else None

    rows, review = [], []
    for _, r in df.iterrows():
        st_names, d_pairs = admin_units(r, gid1)
        if not st_names and not d_pairs and isinstance(r.get("Location"), str):
            st_keys, d_pairs = parse_location(r["Location"], lookup)
            from_text = True
        else:
            st_keys = [k for k in (state_key(s) for s in st_names) if k]
            d_pairs = [(n, state_key(st)) for n, st in d_pairs]
            from_text = False
            if isinstance(r.get("Location"), str):  # the units can miss a state the text names
                st_keys += [k for k in parse_location(r["Location"], lookup)[0]
                            if k not in st_keys]
        listed = list(dict.fromkeys(st_keys + [st for _, st in d_pairs if st]))
        base = {"disno": r["DisNo."]}
        matched_states, matched_ids = set(), set()
        for dn, own in d_pairs:
            hit = match(dn, own, listed)
            if hit is None:
                if not from_text or state_key(dn) is None:
                    review.append({**base, "name": dn, "states": ";".join(listed),
                                   "match": None, "method": "unmatched", "score": np.nan})
                continue
            did, method, score = hit
            if from_text and method == "exact":
                method = "exact_text"  # free text: right name, but worth a look
            matched_states.add(normalise(id_state[did]))
            if did in matched_ids:
                continue
            matched_ids.add(did)
            rows.append({**base, "geo_level": "district", "district_id": int(did),
                         "state": id_state[did], "match_method": method, "match_score": score})
            if method != "exact":
                review.append({**base, "name": dn, "states": ";".join(listed), "match": did,
                               "method": method, "score": score})
        for sk in st_keys:
            if sk not in matched_states:
                rows.append({**base, "geo_level": "state", "district_id": pd.NA,
                             "state": states[sk], "match_method": "state_only",
                             "match_score": np.nan})
                matched_states.add(sk)
        if not matched_states:
            rows.append({**base, "geo_level": "country", "district_id": pd.NA, "state": None,
                         "match_method": "no_location", "match_score": np.nan})
    return pd.DataFrame(rows), pd.DataFrame(review)


def link_events(rec: pd.DataFrame, storms: pd.DataFrame | None, gfd: pd.DataFrame | None,
                slack_days: int = 3) -> pd.DataFrame:
    """Attach the IMD storm (by name, else by date overlap) and the GFD event with the
    largest date overlap to each record."""
    rec = rec.copy()
    rec["imd_event_id"] = None
    rec["gfd_event_id"] = None
    slack = pd.Timedelta(days=slack_days)
    for i, r in rec.iterrows():
        if r.start_date is None or pd.isna(r.start_date):
            continue
        end = r.end_date if pd.notna(r.end_date) else r.start_date
        if r.hazard_type == "cyclone" and storms is not None:
            name = normalise(r.event_name) if isinstance(r.event_name, str) else ""
            by_name = storms[storms.name.fillna("").map(normalise).map(
                lambda n, name=name: bool(n) and n in name)]
            by_name = by_name[by_name.start_time.dt.year == r.start_date.year]
            cand = by_name if len(by_name) else storms[
                (storms.start_time <= end + slack) & (storms.end_time >= r.start_date - slack)
                & storms.landfall_time.notna()
            ]
            if len(cand) == 1:
                rec.at[i, "imd_event_id"] = f"IMD-{cand.storm_id.iloc[0]}"
        if gfd is not None:
            ov = gfd.ended.clip(upper=end + slack) - gfd.began.clip(lower=r.start_date - slack)
            ov = ov.dt.days
            if (ov >= 0).any():
                rec.at[i, "gfd_event_id"] = f"GFD-{int(gfd.dfo_id[ov.idxmax()])}"
    return rec


def build(path: Path) -> list[Path]:
    df = read_export(path)
    rec = pd.DataFrame({
        "disno": df["DisNo."],
        "hazard_type": df["Disaster Type"].map(TYPES),
        "subtype": df.get("Disaster Subtype"),
        "event_name": df.get("Event Name"),
    })
    starts = [_date(*v, end=False) for v in df[["Start Year", "Start Month", "Start Day"]].values]
    ends = [_date(*v, end=True) for v in df[["End Year", "End Month", "End Day"]].values]
    rec["start_date"] = [s[0] for s in starts]
    rec["end_date"] = [e[0] for e in ends]
    rec["date_precision"] = [s[1] for s in starts]
    for src, dst in NUMERIC.items():
        rec[dst] = pd.to_numeric(df.get(src), errors="coerce")
    rec["start_date"] = pd.to_datetime(rec.start_date)
    rec["end_date"] = pd.to_datetime(rec.end_date)

    storms_path = config.path("processed") / "cyclone_storms.parquet"
    storms = pd.read_parquet(storms_path) if storms_path.exists() else None
    if storms is not None:
        storms["start_time"] = pd.to_datetime(storms.start_time)
        storms["end_time"] = pd.to_datetime(storms.end_time)
    gfd_path = config.path("events") / "gfd_india_events.csv"
    gfd = pd.read_csv(gfd_path, parse_dates=["began", "ended"]) if gfd_path.exists() else None
    rec = link_events(rec, storms, gfd)

    geo, review = geocode(df, load_districts())
    geo["district_id"] = geo.district_id.astype("Int64")
    # the finest level the record reaches: "state" flags a record that names no district
    level = geo.geo_level.map({"district": 0, "state": 1, "country": 2})
    geo["record_level"] = level.groupby(geo.disno).transform("min").map(
        {0: "district", 1: "state", 2: "country"})
    out = geo.merge(rec, on="disno", how="left")
    out["data_version"] = config.load("project").get("data_version", "dev")
    processed = config.path("processed")
    processed.mkdir(parents=True, exist_ok=True)
    path_out = processed / OUT_NAME
    out.to_parquet(path_out, index=False)
    rev_path = config.path("interim") / "emdat_geocode_review.csv"
    rev_path.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(rev_path, index=False)
    lv = out.drop_duplicates("disno").record_level.value_counts().to_dict()
    log.info("wrote %s: %d records, levels %s; %d names to review", path_out,
             out.disno.nunique(), lv, len(review))
    return [path_out, rev_path]


def build_default() -> list[Path]:
    """Pipeline step: the newest export in data/raw/emdat, or nothing if none is present."""
    raw = config.path("raw_layers.emdat")
    files = sorted([*raw.glob("*.xlsx"), *raw.glob("*.csv")], key=lambda p: p.stat().st_mtime)
    if not files:
        log.warning("no EM-DAT export in %s; skipping (register at public.emdat.be)", raw)
        return []
    return build(files[-1])


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("path", type=Path)
    a = p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("hazard:emdat", ["project", "paths"]) as outputs:
        outputs += build(a.path)


if __name__ == "__main__":
    main()
