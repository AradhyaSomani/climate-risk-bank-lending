"""Phase 2A: district hazard indicators, kept separate so a reader can see what drives a score.

Flood indicators come from the Global Flood Database footprints (Phase 1E), cyclone
indicators from the IMD best-track exposure table (Phase 1F), and terrain indicators from the
long-run baseline (Phase 1H). Frequencies are per decade of record. The record is short
(GFD 2000-2018, IMD best track since 1982), so frequencies are noisy for districts that
flood or see a storm rarely.

`compute` can drop events after a cut-off year or by id, which the validation in Phase 2C
uses to build out-of-sample versions of the score.

    python -m cri.hazard.indicators
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config
from cri.hazard.baseline import GFD_FIRST, GFD_LAST
from cri.ingest.imd_tracks import grade_from_wind, grade_rank

log = logging.getLogger(__name__)

OUT_NAME = "hazard_indicators.parquet"

FLOOD = ["flood_events_per_decade", "flood_mean_share", "flood_max_share",
         "flood_built_share", "flood_crop_share", "flood_duration_days"]
CYCLONE = ["cyclone_storms_per_decade", "cyclone_max_wind_kt", "cyclone_max_grade_rank",
           "cyclone_landfalls_per_decade"]
TERRAIN = ["perm_water_share", "lowlying_share", "rel_elev_median_m", "slope_mean_deg"]


def event_years(event_ids: Iterable[str], gfd_events: pd.DataFrame | None = None) -> pd.Series:
    """Start year of each event: GFD from the event list, IMD from the storm id."""
    ids = pd.Series(list(dict.fromkeys(event_ids)), dtype="object")
    if gfd_events is None:
        gfd_events = pd.read_csv(config.path("events") / "gfd_india_events.csv")
    gfd = dict(zip("GFD-" + gfd_events.dfo_id.astype(str),
                   pd.to_datetime(gfd_events.began).dt.year, strict=True))
    years = [gfd.get(e) if e.startswith("GFD-")
             else int(e[4:8]) if e.startswith("IMD-") else None for e in ids]
    return pd.Series(years, index=ids.to_numpy(), dtype="Int64")


def _record_years(first: pd.Timestamp, last: pd.Timestamp, before_year: int | None) -> float:
    if before_year is not None:
        last = min(last, pd.Timestamp(f"{before_year}-01-01"))
    return max((last - first).days / 365.25, 0.0)


def flood_indicators(flood: pd.DataFrame, district_ids, hit_share: float,
                     years: float) -> pd.DataFrame:
    """Per district: event frequency, mean and worst flooded share, built-up, cropland and
    duration. Means are over the events that flooded the district above `hit_share`
    (severity when it floods); districts never flooded get zeros."""
    f = flood[flood.source == "gfd"]
    hit = f[f.flooded_share > hit_share].groupby("district_id")
    out = pd.DataFrame(index=pd.Index(district_ids, name="district_id"))
    out["flood_events_hit"] = hit.size()
    out["flood_events_per_decade"] = out.flood_events_hit / years * 10 if years else np.nan
    out["flood_mean_share"] = hit.flooded_share.mean()
    out["flood_max_share"] = f.groupby("district_id").flooded_share.max()
    out["flood_built_share"] = hit.flooded_built_share.mean()
    out["flood_crop_share"] = hit.flooded_crop_share.mean()
    out["flood_duration_days"] = hit.duration_days.mean()
    out["flood_events_mapped"] = f.groupby("district_id").size()
    out = out.fillna(0)
    out[["flood_events_hit", "flood_events_mapped"]] = out[
        ["flood_events_hit", "flood_events_mapped"]].astype(int)
    return out


def cyclone_indicators(cyclone: pd.DataFrame, storms: pd.DataFrame | None, district_ids,
                       radius_km: float, min_grade: str, years: float) -> pd.DataFrame:
    """Per district: storms within the radius rule per decade, the strongest wind and grade at
    closest approach among storms passing within `radius_km`, and landfalls per decade at or
    above `min_grade` (landfall district from the storm table, graded by the strongest wind
    while over that district; the baseline table grades by the wind at the landfall time,
    which can be a class lower)."""
    out = pd.DataFrame(index=pd.Index(district_ids, name="district_id"))
    w = cyclone[cyclone.within_radius]
    out["cyclone_storms_within"] = w.groupby("district_id").event_id.nunique()
    out["cyclone_storms_per_decade"] = out.cyclone_storms_within / years * 10 if years else np.nan
    near = cyclone[cyclone.track_dist_km <= radius_km]
    out["cyclone_max_wind_kt"] = near.groupby("district_id").wind_kt_closest.max()
    out = out.fillna({"cyclone_storms_within": 0, "cyclone_storms_per_decade": 0,
                      "cyclone_max_wind_kt": 0})
    grade = grade_from_wind(out.cyclone_max_wind_kt.where(out.cyclone_max_wind_kt > 0))
    out["cyclone_max_grade"] = grade.to_numpy()
    out["cyclone_max_grade_rank"] = [grade_rank(g) + 1 for g in grade]  # 0 = no storm nearby
    out["cyclone_landfalls_per_decade"] = 0.0
    if storms is not None and len(storms):
        s = storms.dropna(subset=["landfall_district"])
        s = s.assign(district_id=s.landfall_district.astype(int))
        at = s.merge(cyclone[["event_id", "district_id", "grade_closest"]],
                     on=["event_id", "district_id"], how="left")
        strong = at[at.grade_closest.map(grade_rank) >= grade_rank(min_grade)]
        n = strong.groupby("district_id").size().reindex(out.index).fillna(0)
        out["cyclone_landfalls_per_decade"] = n / years * 10 if years else np.nan
    out["cyclone_storms_within"] = out.cyclone_storms_within.astype(int)
    return out


def compute(
    flood: pd.DataFrame | None,
    cyclone: pd.DataFrame | None,
    baseline: pd.DataFrame | None,
    district_ids,
    storms: pd.DataFrame | None = None,
    before_year: int | None = None,
    exclude_events: Iterable[str] = (),
    gfd_events: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """All indicators per district. `before_year` keeps only events starting before that
    year (and shortens the record to match); `exclude_events` drops events by id."""
    hz = config.load("hazard")
    exclude = set(exclude_events)
    out = pd.DataFrame(index=pd.Index(sorted(district_ids), name="district_id"))

    def keep(df: pd.DataFrame) -> pd.DataFrame:
        df = df[~df.event_id.isin(exclude)]
        if before_year is not None:
            yr = event_years(df.event_id.unique(), gfd_events)
            df = df[df.event_id.map(yr).lt(before_year).fillna(False).to_numpy(dtype=bool)]
        return df

    if flood is not None:
        years = _record_years(GFD_FIRST, GFD_LAST, before_year)
        out = out.join(flood_indicators(keep(flood), out.index,
                                        hz["flood"]["event_hit_share"], years))
        out["gfd_record_years"] = round(years, 2)
    if cyclone is not None:
        if storms is not None and len(storms):
            first = pd.Timestamp(storms.start_time.min()).tz_localize(None)
            last = pd.Timestamp(storms.end_time.max()).tz_localize(None)
            storms = storms[storms.event_id.isin(set(keep(storms).event_id))]
        else:
            t = pd.to_datetime(cyclone.closest_time).dt.tz_localize(None)
            first, last = t.min(), t.max()
        years = _record_years(first, last, before_year)
        out = out.join(cyclone_indicators(keep(cyclone), storms, out.index,
                                          hz["cyclone"]["radius_km"],
                                          hz["cyclone"]["min_grade"], years))
        out["imd_record_years"] = round(years, 2)
    if baseline is not None:
        cols = [c for c in TERRAIN if c in baseline.columns]
        out = out.join(baseline.set_index("district_id")[cols])
    return out.reset_index()


def load_inputs(processed: Path | None = None) -> dict:
    processed = processed or config.path("processed")

    def read(name):
        p = processed / name
        return pd.read_parquet(p) if p.exists() else None

    return {
        "flood": read("flood_extent_district_event.parquet"),
        "cyclone": read("cyclone_exposure_district_event.parquet"),
        "storms": read("cyclone_storms.parquet"),
        "baseline": read("hazard_baseline_district.parquet"),
    }


def build(before_year: int | None = None, exclude_events: Iterable[str] = ()) -> list[Path]:
    from cri.geo.districts import load_districts

    ids = load_districts().district_id
    out = compute(district_ids=ids, before_year=before_year, exclude_events=exclude_events,
                  **load_inputs())
    out["data_version"] = config.load("project").get("data_version", "dev")
    path = config.path("processed") / OUT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    log.info("wrote %s (%d districts, %d columns)", path, len(out), out.shape[1])
    return [path]


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("hazard:indicators", ["project", "paths", "hazard"]) as outputs:
        outputs += build()


if __name__ == "__main__":
    main()
