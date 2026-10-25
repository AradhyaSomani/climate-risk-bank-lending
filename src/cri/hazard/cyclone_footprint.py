"""Phase 1F: cyclone exposure per district per storm from the IMD best track.

For each storm the track is interpolated to a fixed time step, then for every district we
record the distance from the district polygon to the track, the time of closest approach,
the track wind and IMD grade at that time, and the storm's first landfall on Indian land.
`within_radius` applies the simple rule in configs/hazard.yaml (distance and minimum grade).
There are no wind radii in the IMD record, so this is a distance-and-intensity footprint,
not a wind field.

    python -m cri.hazard.cyclone_footprint
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from cri import config, contracts
from cri.geo.districts import load_districts
from cri.geo.land import coastal_mask, foreign_land
from cri.ingest.imd_tracks import grade_from_wind, grade_rank, load_tracks

log = logging.getLogger(__name__)

OUT_NAME = "cyclone_exposure_district_event.parquet"
STORMS_NAME = "cyclone_storms.parquet"


def imd_event_id(storm_id: str) -> str:
    return f"IMD-{storm_id}"


def densify(track: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Linear interpolation of lat, lon and wind to a regular time step."""
    t = track.set_index("time")[["lat", "lon", "wind_kt"]].astype(float)
    t = t[~t.index.duplicated()]
    grid = pd.date_range(t.index.min(), t.index.max(), freq=f"{minutes}min")
    full = t.reindex(t.index.union(grid)).interpolate(method="time").loc[grid]
    full.index.name = "time"
    return full.reset_index()


def storm_footprint(
    track: pd.DataFrame,
    districts_m: gpd.GeoDataFrame,
    india_m,
    minutes: int,
    max_report_km: float,
    foreign_m=None,
) -> tuple[pd.DataFrame, dict]:
    """District rows for one storm plus a storm summary (landfall time and district)."""
    track = track.dropna(subset=["wind_kt"])
    if len(track) < 2:
        return pd.DataFrame(), {"landfall_time": pd.NaT, "landfall_district": None,
                                "min_dist_mainland_km": np.nan}
    pts = densify(track, minutes)
    excluded = set(config.load("hazard")["cyclone"]["landfall_exclude_states"])
    metric = districts_m.crs
    geo = gpd.GeoSeries(gpd.points_from_xy(pts.lon, pts.lat), crs="EPSG:4326").to_crs(metric)
    p = geo.to_numpy()

    on_land = shapely.contains_xy(india_m, geo.x.to_numpy(), geo.y.to_numpy())
    landfall_time, landfall_district = pd.NaT, None
    from_sea = ~on_land[:-1]
    if foreign_m is not None:
        # entering India overland (e.g. from Bangladesh) is not a landfall in India
        from_sea &= ~shapely.contains_xy(foreign_m, geo.x.to_numpy()[:-1], geo.y.to_numpy()[:-1])
    crossing = np.flatnonzero(on_land[1:] & from_sea)
    if len(crossing):
        k = crossing[0] + 1
        landfall_time = pts.time.iloc[k]
        hit = districts_m.sindex.query(p[k], predicate="intersects")
        hit = [h for h in hit if districts_m.state.iloc[h] not in excluded]
        if "coastal" in districts_m and len(hit) and not districts_m.coastal.iloc[hit[0]]:
            # first Indian district is inland: the storm crossed the coast of another
            # country (coarse old fixes can hide that between two points)
            hit, landfall_time = [], pd.NaT
        if len(hit):
            landfall_district = int(districts_m.district_id.iloc[hit[0]])

    summary = {"landfall_time": landfall_time, "landfall_district": landfall_district,
               "min_dist_mainland_km": float(shapely.distance(p, india_m).min() / 1000.0)}

    # only districts whose bounding box is within reach of the track
    reach = shapely.box(*shapely.bounds(shapely.multipoints(p))).buffer(max_report_km * 1000)
    cand = districts_m.sindex.query(reach, predicate="intersects")
    if len(cand) == 0:
        return pd.DataFrame(), summary
    districts_m = districts_m.iloc[np.sort(cand)]
    polys = districts_m.geometry.to_numpy()
    shapely.prepare(polys)
    dist = shapely.distance(p[:, None], polys[None, :]) / 1000.0  # km, (n_points, n_districts)
    dmin = dist.min(axis=0)
    # closest approach: among the nearest points (ties when the track crosses the district),
    # take the strongest wind
    near = dist <= dmin[None, :] + 1e-6
    wind = np.where(near, pts.wind_kt.to_numpy()[:, None], -np.inf)
    k = wind.argmax(axis=0)

    keep = dmin <= max_report_km
    rows = pd.DataFrame(
        {
            "district_id": districts_m.district_id.to_numpy()[keep],
            "track_dist_km": dmin[keep],
            "closest_time": pts.time.to_numpy()[k[keep]],
            "wind_kt_closest": pts.wind_kt.to_numpy()[k[keep]],
        }
    )
    rows["grade_closest"] = grade_from_wind(rows.wind_kt_closest).to_numpy()
    rows["landfall_time"] = landfall_time
    return rows, summary


def build(storm_ids: list[str] | None = None) -> list[Path]:
    hz = config.load("hazard")["cyclone"]
    proj = config.load("project")
    tracks = load_tracks()
    storms = tracks.groupby("storm_id").agg(
        name=("name", "first"), basin=("basin", "first"), start_time=("time", "min"),
        end_time=("time", "max"), max_wind_kt=("wind_kt", "max"), n_fixes=("time", "size"),
    )
    storms["peak_grade"] = grade_from_wind(storms.max_wind_kt).to_numpy()
    storms = storms[storms.n_fixes >= 2]
    if storm_ids:
        storms = storms.loc[storm_ids]

    districts_m = load_districts().to_crs(proj["crs"]["metric"])
    # landfall means the mainland coast: island territories are crossed by many storms
    # long before landfall (Hudhud and Phailin both pass over the Andamans)
    mainland = ~districts_m.state.isin(hz["landfall_exclude_states"])
    india_m = shapely.union_all(districts_m.geometry[mainland].to_numpy())
    india_m = shapely.simplify(india_m, 500)  # 0.5 km tolerance is ample for landfall
    shapely.prepare(india_m)
    districts_m["coastal"] = coastal_mask(districts_m, hz["coastal_within_km"])
    foreign_m = foreign_land(shapely.union_all(districts_m.geometry.to_numpy()), districts_m.crs)
    foreign_m = shapely.simplify(foreign_m, 500)
    shapely.prepare(foreign_m)

    parts, summaries = [], []
    for sid in storms.index:
        rows, summary = storm_footprint(
            tracks[tracks.storm_id == sid], districts_m, india_m,
            hz["densify_minutes"], hz["max_report_km"], foreign_m,
        )
        summaries.append({"event_id": imd_event_id(sid), "storm_id": sid, **summary})
        if rows.empty:
            continue
        rows.insert(0, "event_id", imd_event_id(sid))
        parts.append(rows)

    out = pd.concat(parts, ignore_index=True)
    min_rank = grade_rank(hz["min_grade"])
    out["within_radius"] = (out.track_dist_km <= hz["radius_km"]) & (
        out.grade_closest.map(grade_rank) >= min_rank
    )
    out["closest_time"] = pd.to_datetime(out.closest_time).dt.tz_localize("UTC")
    out["landfall_time"] = pd.to_datetime(out.landfall_time).dt.tz_localize("UTC")
    out["data_version"] = proj.get("data_version", "dev")

    spec = contracts.get_table("C3", "cyclone_exposure_district_event")
    out = out[list(spec.columns)].sort_values(["event_id", "district_id"]).reset_index(drop=True)
    errs = contracts.validate_frame(out, spec)
    if errs:
        raise ValueError("cyclone exposure fails contract C3:\n" + "\n".join(errs))

    processed = config.path("processed")
    processed.mkdir(parents=True, exist_ok=True)
    path = processed / OUT_NAME
    out.to_parquet(path, index=False)

    st = storms.reset_index().merge(pd.DataFrame(summaries), on="storm_id", how="left")
    st["landfall_time"] = pd.to_datetime(st.landfall_time).dt.tz_localize("UTC")
    spath = processed / STORMS_NAME
    st.to_parquet(spath, index=False)
    log.info("wrote %s (%d rows, %d storms) and %s", path, len(out), out.event_id.nunique(), spath)
    return [path, spath]


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--storms", nargs="*", help="IMD storm ids, e.g. 2019-002 (default: all)")
    a = p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("hazard:cyclone_footprint", ["project", "paths", "hazard"]) as outputs:
        outputs += build(a.storms)


if __name__ == "__main__":
    main()
