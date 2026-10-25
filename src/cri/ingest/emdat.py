"""Phase 1G: EM-DAT India flood and storm records, geocoded to Census 2011 districts.

Input: the EM-DAT public table exported as xlsx (or csv) from public.emdat.be after free
registration, saved under data/raw/emdat/. EM-DAT's terms forbid redistributing the raw
file, so it is never committed and only derived counts and flags are published.

Location comes from the `GADM Admin Units` column (JSON, keys gid_1/name_1 and
gid_2/name_2), falling back to the deprecated `Admin Units` column (adm1_name/adm2_name)
and finally to the free-text `Location`. Admin-2 names are matched to districts within the
record's states; records that only name a state are kept with geo_level = "state".
Non-exact matches go to data/interim/emdat_geocode_review.csv for a manual check.

    python -m cri.ingest.emdat data/raw/emdat/emdat_india.xlsx
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config
from cri.geo.districts import load_districts
from cri.geo.names import best_match, normalise

log = logging.getLogger(__name__)

OUT_NAME = "disaster_records.parquet"
TYPES = {"Flood": "flood", "Storm": "cyclone"}
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
    return df.reset_index(drop=True)


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


def admin_units(row: pd.Series) -> tuple[list[str], list[str]]:
    """(state names, district names) from the GADM or legacy admin-unit JSON."""
    for col, k1, k2 in (("GADM Admin Units", "name_1", "name_2"),
                        ("Admin Units", "adm1_name", "adm2_name")):
        raw = row.get(col)
        if isinstance(raw, str) and raw.strip().startswith("["):
            units = json.loads(raw)
            states = [u[k1] for u in units if k1 in u and k2 not in u]
            districts = [u[k2] for u in units if k2 in u]
            states += [u[k1] for u in units if k2 in u and k1 in u]
            return sorted(set(states)), sorted(set(districts))
    return [], []


def geocode(df: pd.DataFrame, districts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long table: one row per record and district (or per record and state)."""
    states = {normalise(s): s for s in districts.state.unique()}
    by_state = {
        normalise(s): {normalise(n): i for n, i in zip(g.name, g.district_id, strict=True)}
        for s, g in districts.groupby("state")
    }
    all_d = {normalise(n): i for n, i in zip(districts.name, districts.district_id, strict=True)}
    id_state = dict(zip(districts.district_id, districts.state, strict=True))

    rows, review = [], []
    for _, r in df.iterrows():
        st_names, d_names = admin_units(r)
        if not st_names and not d_names and isinstance(r.get("Location"), str):
            # free text: split on commas and semicolons and try each piece as a district
            # or a state; everything found this way is reviewed by hand
            pieces = [p.strip() for p in r["Location"].replace(";", ",").split(",") if p.strip()]
            for p in pieces:
                (st_names if normalise(p) in states else d_names).append(p)
        st_keys = [k for k in (best_match(s, {k: k for k in states}) for s in st_names) if k]
        st_keys = [k[0] for k in st_keys]
        base = {"disno": r["DisNo."]}
        matched_states = set()
        for dn in d_names:
            pool = {}
            for sk in st_keys:
                pool.update(by_state.get(sk, {}))
            hit = best_match(dn, pool or all_d)
            if hit is None:
                review.append({**base, "name": dn, "states": ";".join(st_names), "match": None,
                               "method": "unmatched", "score": np.nan})
                continue
            did, method, score = hit
            matched_states.add(normalise(id_state[did]))
            rows.append({**base, "geo_level": "district", "district_id": int(did),
                         "state": id_state[did], "match_method": method, "match_score": score})
            if method != "exact":
                review.append({**base, "name": dn, "states": ";".join(st_names), "match": did,
                               "method": method, "score": score})
        for sk in st_keys:
            if sk not in matched_states:
                rows.append({**base, "geo_level": "state", "district_id": pd.NA,
                             "state": states[sk], "match_method": "state_only",
                             "match_score": np.nan})
        if not st_keys and not d_names:
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
    out = geo.merge(rec, on="disno", how="left")
    out["data_version"] = config.load("project").get("data_version", "dev")
    processed = config.path("processed")
    processed.mkdir(parents=True, exist_ok=True)
    path_out = processed / OUT_NAME
    out.to_parquet(path_out, index=False)
    rev_path = config.path("interim") / "emdat_geocode_review.csv"
    rev_path.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(rev_path, index=False)
    lv = out.drop_duplicates("disno").geo_level.value_counts().to_dict()
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
