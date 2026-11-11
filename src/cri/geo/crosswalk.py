"""RBI district names to Census 2011 districts (Phase 1 B, contract C1 `crosswalk_rbi_to_c2011`).

Every (state, district) label that carries a figure in RBI's quarterly district statement is
mapped to the Census 2011 district(s) it belongs to, for the quarters it is used:

- the same district under the same or another spelling or a later name: weight 1;
- a district created after 2011: weight 1 to the Census 2011 district it was mostly carved
  from (configs/crosswalk.yaml `new_districts`);
- a district that was split between 2004 and 2011 into Census 2011 districts: until each
  child first appears in RBI's tables, the parent's label is shared between the parent and
  the children not yet reported, by Census 2011 population (`pre_2011_children`).

Names are resolved from configs/crosswalk.yaml, then configs/district_aliases.yaml, then an
exact or normalised match. Nothing is matched by fuzzy score alone: an unresolved name stops
the build and is listed with a fuzzy suggestion in data/interim/crosswalk_review.csv. The
review file also lists every non-exact decision, so each one can be checked by hand, and, for
each new label, the districts whose office counts dropped in the quarter it first appeared.

    python -m cri.geo.crosswalk
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cri import config
from cri.geo import names

log = logging.getLogger(__name__)

XW_FILE = "crosswalk_rbi_to_c2011.parquet"
REVIEW_FILE = "crosswalk_review.csv"
COLUMNS = ["rbi_name", "rbi_state", "valid_from", "valid_to", "district_id", "weight",
           "match_type"]


class UnresolvedNames(ValueError):
    pass


def _kind(rbi_name: str, target: str) -> str:
    """'fuzzy' when a decided match is also a close spelling (difflib ratio >= 0.8), else
    'manual' (a rename or a new district)"""
    close = names.best_match(rbi_name, {names.normalise(target): 1}, cutoff=0.8)
    return "fuzzy" if close else "manual"


@dataclass
class Resolver:
    """Resolve an RBI (state, district) label to one Census 2011 district."""

    master: pd.DataFrame          # district_id, name, state
    cfg: dict                     # configs/crosswalk.yaml
    aliases: dict                 # configs/district_aliases.yaml

    def __post_init__(self):
        self.states_2011 = sorted(self.master.state.unique())
        self.by_state = {
            s: {names.normalise(n): int(i) for n, i in zip(g.name, g.district_id, strict=True)}
            for s, g in self.master.groupby("state")
        }
        m = self.master
        self.id_by_name = {(s, n): int(i) for s, n, i in
                           zip(m.state, m.name, m.district_id, strict=True)}

    def states(self, rbi_state: str) -> list[str]:
        mapped = (self.cfg.get("states") or {}).get(rbi_state.strip().upper())
        if mapped is not None:
            return mapped if isinstance(mapped, list) else [mapped]
        cands = {names.normalise(s): s for s in self.states_2011}
        hit = names.best_match(rbi_state, cands, cutoff=1.0)
        if hit is None:
            raise UnresolvedNames(f"RBI state {rbi_state!r} matches no Census 2011 state; "
                                  "add it under `states` in configs/crosswalk.yaml")
        return [hit[0]]

    def _target(self, state: str, name_2011: str, where: str) -> int:
        key = (state, name_2011)
        if key not in self.id_by_name:
            raise ValueError(f"{where}: {name_2011!r} is not a Census 2011 district of {state}")
        return self.id_by_name[key]

    def resolve(self, rbi_state: str, rbi_name: str) -> tuple[int, str, str] | None:
        """(district_id, match_type, source) or None when nothing resolves it."""
        key = names.normalise(rbi_name)
        for state in self.states(rbi_state):
            wide = (self.cfg.get("state_wide_labels") or {}).get(state) or []
            if key in {names.normalise(w) for w in wide}:
                ids = sorted(self.master.loc[self.master.state == state, "district_id"])
                return int(ids[0]), "split", "state_wide_labels"
            cfg_names = {names.normalise(k): v
                         for k, v in ((self.cfg.get("names") or {}).get(state) or {}).items()}
            if key in cfg_names:
                target = cfg_names[key]
                return (self._target(state, target, "crosswalk.yaml names"),
                        _kind(rbi_name, target), "names")
            new = {names.normalise(k): v for k, v in
                   ((self.cfg.get("new_districts") or {}).get(state) or {}).items()}
            if key in new:
                return (self._target(state, new[key]["parent"], "crosswalk.yaml new_districts"),
                        "manual", "new_districts")
            hit = names.best_match(rbi_name, self.by_state.get(state, {}), cutoff=1.0)
            if hit is not None:
                kind = "exact" if hit[1] == "exact" else "normalized"
                return int(hit[0]), kind, "boundary file"
            al = {names.normalise(k): v for k, v in
                  ((self.aliases.get("districts") or {}).get(state) or {}).items()}
            if key in al:
                return (self._target(state, al[key], "district_aliases.yaml"),
                        _kind(rbi_name, al[key]), "aliases")
        return None

    def suggest(self, rbi_state: str, rbi_name: str) -> tuple[str, float] | None:
        cands = {}
        for state in self.states(rbi_state):
            cands.update(self.by_state.get(state, {}))
        hit = names.best_match(rbi_name, cands, cutoff=0.6)
        if hit is None:
            return None
        name = self.master.set_index("district_id").name.get(hit[0])
        return name, hit[2]


def label_spans(rbi: pd.DataFrame) -> pd.DataFrame:
    """First and last quarter in which each RBI label carries an amount or an office count."""
    has = rbi[rbi.amount_cr.notna() | rbi.n_offices.notna()]
    spans = (has.groupby(["rbi_state", "rbi_district"]).quarter_end
             .agg(first_q="min", last_q="max").reset_index())
    return spans


def _offices(rbi: pd.DataFrame) -> pd.DataFrame:
    """Offices per label (rows) and quarter (columns); offices repeat on both measures."""
    one = rbi.drop_duplicates(["rbi_state", "rbi_district", "quarter_end"])
    return one.pivot_table(index=["rbi_state", "rbi_district"], columns="quarter_end",
                           values="n_offices", aggfunc="first")


def office_drop(offices: pd.DataFrame, rbi_state: str, first_q, top: int = 3) -> str:
    """Labels of the same RBI state whose office count fell most when `first_q` began."""
    qs = list(offices.columns)
    if first_q not in qs or qs.index(first_q) == 0 or rbi_state not in offices.index:
        return ""
    prev = qs[qs.index(first_q) - 1]
    same = offices.loc[rbi_state]
    delta = (same[first_q] - same[prev]).dropna().sort_values()
    return "; ".join(f"{k} {int(v)}" for k, v in delta.head(top).items() if v < 0)


def _children(cfg: dict, resolver: Resolver) -> dict[int, list[int]]:
    """Census 2011 parent id -> ids of its children created between 2004 and 2011."""
    out: dict[int, list[int]] = {}
    for state, entries in (cfg.get("pre_2011_children") or {}).items():
        for child, spec in entries.items():
            p = resolver._target(state, spec["parent"], "pre_2011_children")
            c = resolver._target(state, child, "pre_2011_children")
            out.setdefault(p, []).append(c)
    return out


def build_crosswalk(rbi: pd.DataFrame, master: pd.DataFrame, cfg: dict, aliases: dict,
                    review_path: Path | None = None) -> pd.DataFrame:
    resolver = Resolver(master[["district_id", "name", "state"]], cfg, aliases)
    spans = label_spans(rbi)
    last_quarter = rbi.quarter_end.max()
    offices = _offices(rbi)

    rows, review, unresolved = [], [], []
    for r in spans.itertuples(index=False):
        hit = resolver.resolve(r.rbi_state, r.rbi_district)
        rec = {"rbi_state": r.rbi_state, "rbi_name": r.rbi_district,
               "first_quarter": r.first_q.date(), "last_quarter": r.last_q.date()}
        if hit is None:
            sug = resolver.suggest(r.rbi_state, r.rbi_district)
            unresolved.append({**rec, "match_type": "UNRESOLVED",
                               "suggestion": sug[0] if sug else "",
                               "suggestion_score": sug[1] if sug else None,
                               "office_drop": office_drop(offices, r.rbi_state, r.first_q)})
            continue
        did, kind, source = hit
        rows.append({"rbi_name": r.rbi_district, "rbi_state": r.rbi_state,
                     "valid_from": r.first_q, "valid_to": r.last_q, "district_id": did,
                     "weight": 1.0, "match_type": kind})
        if kind != "exact":
            review.append({**rec, "match_type": kind, "decided_in": source, "district_id": did,
                           "district_name": resolver.master.set_index("district_id").name[did],
                           "office_drop": (office_drop(offices, r.rbi_state, r.first_q)
                                           if source == "new_districts" else "")})
    if review_path is not None:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(unresolved + review).to_csv(review_path, index=False)
    if unresolved:
        listing = ", ".join(f"{u['rbi_name']} ({u['rbi_state']})" for u in unresolved)
        raise UnresolvedNames(f"{len(unresolved)} RBI district names are not mapped: {listing}. "
                              f"See {review_path}; add each to configs/crosswalk.yaml")

    xw = pd.DataFrame(rows)
    xw = _share_pre_2011(xw, master, _children(cfg, resolver))
    xw = _share_state_wide(xw, master, cfg.get("state_wide_labels") or {}, resolver)
    xw["valid_to"] = xw.valid_to.where(xw.valid_to < last_quarter)
    return xw[COLUMNS].sort_values(["rbi_state", "rbi_name", "valid_from", "district_id"]) \
        .reset_index(drop=True)


def _share_pre_2011(xw: pd.DataFrame, master: pd.DataFrame,
                    children: dict[int, list[int]]) -> pd.DataFrame:
    """Share parent labels with Census 2011 children until the children are reported."""
    pop = master.set_index("district_id").population
    first_seen = xw.groupby("district_id").valid_from.min()
    out = [xw[~xw.district_id.isin(children)]]
    for parent, kids in children.items():
        own = xw[xw.district_id == parent]
        starts = {k: first_seen.get(k) for k in kids}
        never = [k for k, s in starts.items() if s is None or pd.isna(s)]
        if never:
            raise ValueError(f"Census 2011 districts {never} never appear in the RBI data; "
                             "remove them from pre_2011_children")
        for r in own.itertuples(index=False):
            cuts = sorted({s for s in starts.values() if r.valid_from < s <= r.valid_to})
            bounds = [r.valid_from, *cuts]
            for i, lo in enumerate(bounds):
                hi = (bounds[i + 1] - pd.offsets.QuarterEnd(1)) if i + 1 < len(bounds) \
                    else r.valid_to
                inside = [k for k, s in starts.items() if s > lo]
                group = [parent, *inside]
                total = pop[group].sum()
                for d in group:
                    out.append(pd.DataFrame([{
                        "rbi_name": r.rbi_name, "rbi_state": r.rbi_state, "valid_from": lo,
                        "valid_to": hi, "district_id": d,
                        "weight": float(pop[d] / total) if inside else 1.0,
                        "match_type": "split" if inside else r.match_type}]))
    return pd.concat(out, ignore_index=True)


def _share_state_wide(xw: pd.DataFrame, master: pd.DataFrame, labels: dict,
                      resolver: Resolver) -> pd.DataFrame:
    """Share a label that stands for a whole state among its districts by population."""
    for state, wanted in labels.items():
        districts = master[master.state == state]
        if districts.empty:
            raise ValueError(f"state_wide_labels: no Census 2011 state {state!r}")
        share = districts.population / districts.population.sum()
        keys = {names.normalise(w) for w in wanted}
        hit = xw.rbi_name.map(names.normalise).isin(keys) & xw.district_id.isin(
            districts.district_id)
        rows = []
        for r in xw[hit].itertuples(index=False):
            for d, w in zip(districts.district_id, share, strict=True):
                rows.append({**r._asdict(), "district_id": int(d), "weight": float(w),
                             "match_type": "split"})
        xw = pd.concat([xw[~hit], pd.DataFrame(rows)], ignore_index=True)
    return xw


def build(out: Path | None = None) -> Path:
    from cri.ingest.rbi_bsr import interim_path

    out = out or config.path("processed") / XW_FILE
    rbi = pd.read_parquet(interim_path())
    master = pd.read_parquet(config.path("district_geometry.preferred"),
                             columns=["district_id", "name", "state", "population"])
    xw = build_crosswalk(rbi, master, config.load("crosswalk"), config.load("district_aliases"),
                         review_path=config.path("interim") / REVIEW_FILE)
    xw.to_parquet(out, index=False)
    log.info("crosswalk: %d rows for %d RBI labels; %d shared by population; written to %s",
             len(xw), xw[["rbi_state", "rbi_name"]].drop_duplicates().shape[0],
             int((xw.match_type == "split").sum()), out)
    return out


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    print(build())


if __name__ == "__main__":
    main()
