"""Phase 3A: event catalogue and per-district treatment flags (contract C4).

Events come from data/events/events_candidates.csv (dates and the matching GFD and IMD ids
were checked in Phase 0). Footprints come from the Phase 1 tables:

- floods: `flood_extent_district_event` for the event's footprint (GFD now, Sentinel-1 once
  exported). Treated above `flood.treated_share` of district area.
- cyclones: `cyclone_exposure_district_event` for the IMD storm. Treated within
  `cyclone.treated_km` of the track at `cyclone.treated_grade` or stronger.

The exclusion zone (kept out of the main control pool) holds districts that were partly
affected or share a border with a treated district. The impact quarter is the quarter of
landfall for cyclones and of the start date for floods. Events with no footprint yet (Kerala
2018, Uttarakhand 2013) stay in `events.parquet` with the reason in `source`, and have no
district rows until a footprint exists.

    python -m cri.events.catalogue
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config, contracts
from cri.ingest.imd_tracks import grade_rank

log = logging.getLogger(__name__)


def quarter_end(ts) -> pd.Timestamp:
    return (pd.Timestamp(ts).to_period("Q").end_time).normalize()


def neighbours(edges: pd.DataFrame, ids) -> set[int]:
    ids = set(ids)
    a = edges[edges.a.isin(ids)].b
    b = edges[edges.b.isin(ids)].a
    return (set(a) | set(b)) - ids


def flood_rows(event_id: str, footprint: pd.DataFrame, rules: dict,
               in_states: pd.Series | None = None) -> pd.DataFrame:
    """`in_states`: True for districts in the event's states (index = district_id)."""
    f = footprint
    inside = (f.district_id.map(in_states).fillna(False).astype(bool).to_numpy()
              if in_states is not None else np.ones(len(f), dtype=bool))
    return pd.DataFrame({
        "event_id": event_id, "district_id": f.district_id.astype(int),
        "flooded_share": f.flooded_share, "flooded_built_share": f.flooded_built_share,
        "track_dist_km": np.nan, "max_wind_kt": np.nan,
        "treated": (f.flooded_share > rules["treated_share"]).to_numpy() & inside,
        "heavily_treated": (f.flooded_share > rules["heavy_share"]).to_numpy() & inside,
        "partial": f.flooded_share > rules["partial_share"],
    })


def cyclone_rows(event_id: str, exposure: pd.DataFrame, rules: dict) -> pd.DataFrame:
    c = exposure
    rank = c.grade_closest.map(grade_rank)
    return pd.DataFrame({
        "event_id": event_id, "district_id": c.district_id.astype(int),
        "flooded_share": np.nan, "flooded_built_share": np.nan,
        "track_dist_km": c.track_dist_km, "max_wind_kt": c.wind_kt_closest,
        "treated": (c.track_dist_km <= rules["treated_km"])
        & (rank >= grade_rank(rules["treated_grade"])),
        "heavily_treated": (c.track_dist_km <= rules["heavy_km"])
        & (rank >= grade_rank(rules["heavy_grade"])),
        "partial": (c.track_dist_km <= rules["partial_km"])
        & (rank >= grade_rank(rules["partial_grade"])),
    })


def finish(rows: pd.DataFrame, edges: pd.DataFrame | None, use_neighbours: bool) -> pd.DataFrame:
    """Exclusion zone, then keep only districts that are treated or excluded."""
    treated = set(rows.district_id[rows.treated])
    nb = neighbours(edges, treated) if use_neighbours and edges is not None else set()
    missing = sorted(nb - set(rows.district_id))
    if missing:  # neighbours the footprint never reached
        rows = pd.concat([rows, pd.DataFrame({
            "event_id": rows.event_id.iloc[0], "district_id": missing, "treated": False,
            "heavily_treated": False, "partial": False})], ignore_index=True)
    rows = rows.assign(excluded=~rows.treated & (rows.partial | rows.district_id.isin(nb)))
    rows = rows[rows.treated | rows.excluded].drop(columns="partial")
    return rows.reset_index(drop=True)


def build(processed: Path | None = None) -> list[Path]:
    cfg = config.load("events")
    processed = processed or config.path("processed")
    cand = pd.read_csv(config.REPO_ROOT / cfg["candidates"], dtype=str)
    flood = pd.read_parquet(processed / "flood_extent_district_event.parquet")
    cyc = pd.read_parquet(processed / "cyclone_exposure_district_event.parquet")
    storms = pd.read_parquet(processed / "cyclone_storms.parquet")
    edges_path = processed / "district_edges.parquet"
    edges = pd.read_parquet(edges_path) if edges_path.exists() else None
    if edges is None and cfg["exclusion"]["neighbours"]:
        log.warning("district_edges.parquet missing: neighbours not added to the exclusion zone"
                    " (run python -m cri.ml.graph.build)")

    from cri.geo.districts import load_districts

    district_state = load_districts().set_index("district_id").state
    events, parts = [], []
    for ev in cand.itertuples():
        start = pd.Timestamp(ev.start_date)
        impact, source, rows = quarter_end(start), None, None
        if ev.type == "cyclone" and isinstance(ev.imd_storm_id, str):
            eid = f"IMD-{ev.imd_storm_id}"
            st = storms[storms.storm_id == ev.imd_storm_id]
            if len(st) and pd.notna(st.landfall_time.iloc[0]):
                impact = quarter_end(pd.Timestamp(st.landfall_time.iloc[0]).tz_localize(None))
            rows = cyclone_rows(ev.event_id, cyc[cyc.event_id == eid], cfg["cyclone"])
            source = f"IMD best track {ev.imd_storm_id}; dates: {ev.date_source}"
        elif ev.type == "flood":
            fp = pd.DataFrame()
            for src in ("s1_unet", "s1_otsu", "gfd"):  # best available footprint
                key = ev.event_id if src != "gfd" else f"GFD-{ev.gfd_dfo_id}"
                fp = flood[(flood.event_id == key) & (flood.source == src)]
                if len(fp):
                    source = f"{src} footprint {key}; dates: {ev.date_source}"
                    break
            if len(fp):
                in_states = None
                if cfg["flood"].get("restrict_to_states", False):
                    in_states = district_state.isin(ev.states.split(";"))
                rows = flood_rows(ev.event_id, fp, cfg["flood"], in_states)
            else:
                source = f"no footprint yet ({ev.notes.split(';')[0]}); dates: {ev.date_source}"
        if rows is not None and len(rows):
            rows = finish(rows, edges, cfg["exclusion"]["neighbours"])
            parts.append(rows)
        events.append({
            "event_id": ev.event_id, "hazard_type": ev.type, "name": ev.name,
            "start_date": start.date(),
            "end_date": pd.Timestamp(ev.end_date).date() if isinstance(ev.end_date, str) else None,
            "impact_quarter": impact.date(), "states": ev.states, "source": source,
            "emdat_id": None,
        })
    events = pd.DataFrame(events)
    for c in ("start_date", "end_date", "impact_quarter"):
        events[c] = pd.to_datetime(events[c])
    ed = pd.concat(parts, ignore_index=True)
    ed["district_id"] = ed.district_id.astype(int)
    for c in ("treated", "heavily_treated", "excluded"):
        ed[c] = ed[c].astype(bool)

    out = []
    for name, df in (("events", events), ("event_district", ed)):
        spec = contracts.get_table("C4", name)
        df = df[list(spec.columns)]
        errs = contracts.validate_frame(df, spec)
        if errs:
            raise ValueError(f"{name} fails contract C4:\n" + "\n".join(errs))
        path = processed / f"{name}.parquet"
        df.to_parquet(path, index=False)
        out.append(path)
    summary = ed.groupby("event_id").agg(treated=("treated", "sum"),
                                         heavy=("heavily_treated", "sum"),
                                         excluded=("excluded", "sum"))
    log.info("wrote %s and %s\n%s", *out, summary.to_string())
    return out


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("events:catalogue", ["project", "paths", "events"]) as outputs:
        outputs += build()


if __name__ == "__main__":
    main()
