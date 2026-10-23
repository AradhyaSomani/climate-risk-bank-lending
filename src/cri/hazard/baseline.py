"""Phase 1H: long-run hazard baseline per district.

- Flood frequency from the Global Flood Database events already reduced to districts
  (Phase 1E): events that hit the district, and the mean number of times a pixel of the
  district was flooded (sum over events of flooded share), per decade of record.
- Permanent water share from JRC Global Surface Water (occurrence >= 90%).
- Terrain from Copernicus DEM GLO-90: mean elevation, mean slope, share of low-lying land,
  and a crude height-above-drainage proxy (elevation above the district's 5th percentile).
  A true HAND layer needs flow routing (MERIT Hydro through Earth Engine); the proxy is
  labelled as such everywhere it is used.
- Cyclone landfall frequency per coastal district from the IMD track record (Phase 1F).

All rasters are sampled onto one India grid (default 0.005 degrees, about 500 m) and
reduced to districts with exact spherical pixel areas.

    python -m cri.hazard.baseline
"""

from __future__ import annotations

import argparse
import logging
import math
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.errors import RasterioIOError
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds

from cri import config
from cri.geo.districts import load_districts
from cri.hazard import landcover  # noqa: F401  (sets GDAL/curl environment)
from cri.hazard.zonal_stats import district_index, pixel_area_km2

log = logging.getLogger(__name__)

OUT_NAME = "hazard_baseline_district.parquet"
INDIA_BOUNDS = (68.0, 6.0, 98.0, 37.5)  # left, bottom, right, top
GFD_FIRST, GFD_LAST = pd.Timestamp("2000-02-17"), pd.Timestamp("2018-12-10")

JRC_URL = (
    "/vsicurl/https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/"
    "occurrence_{lon}E_{lat}Nv1_4_2021.tif"
)
DEM_URL = (
    "/vsicurl/https://copernicus-dem-90m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_30_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_30_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
)


def india_grid(res: float, bounds=INDIA_BOUNDS):
    left, bottom, right, top = bounds
    width = int(round((right - left) / res))
    height = int(round((top - bottom) / res))
    return from_origin(left, top, res, res), (height, width)


def jrc_tiles(bounds=INDIA_BOUNDS) -> list[str]:
    """JRC 10-degree tiles are named by their top-left corner (e.g. 70E_10N = 70-80E, 0-10N)."""
    left, bottom, right, top = bounds
    lons = range(10 * math.floor(left / 10), 10 * math.ceil(right / 10), 10)
    lats = range(10 * math.floor(bottom / 10) + 10, 10 * math.ceil(top / 10) + 10, 10)
    return [JRC_URL.format(lon=lo, lat=la) for la in lats for lo in lons]


def dem_tiles(bounds=INDIA_BOUNDS) -> list[str]:
    """Copernicus DEM 1-degree tiles named by their bottom-left corner."""
    left, bottom, right, top = bounds
    out = []
    for la in range(math.floor(bottom), math.ceil(top)):
        for lo in range(math.floor(left), math.ceil(right)):
            out.append(DEM_URL.format(ns="N" if la >= 0 else "S", lat=abs(la),
                                      ew="E" if lo >= 0 else "W", lon=abs(lo)))
    return out


def sample_onto_grid(urls: Iterable[str], transform, shape, resampling=Resampling.average,
                     dtype="float32", nodata=np.nan, src_nodata=None) -> np.ndarray:
    """Mosaic remote tiles onto the grid, reading each at about twice the target resolution."""
    out = np.full(shape, nodata, dtype=dtype)
    res = abs(transform.a)
    height, width = shape
    left, top = transform.c, transform.f
    right, bottom = left + res * width, top - res * height
    for url in urls:
        try:
            src = rasterio.open(url)
        except RasterioIOError:
            continue  # tile does not exist (sea)
        with src:
            b = src.bounds
            ib = (max(left, b.left), max(bottom, b.bottom), min(right, b.right), min(top, b.top))
            if ib[0] >= ib[2] or ib[1] >= ib[3]:
                continue
            win = from_bounds(*ib, transform=src.transform)
            factor = max(1, int(res / abs(src.res[0]) / 2))
            oh, ow = max(1, int(win.height / factor)), max(1, int(win.width / factor))
            arr = src.read(1, window=win, out_shape=(oh, ow), resampling=Resampling.average,
                           masked=False).astype("float32")
            if src_nodata is not None:
                arr[arr == src_nodata] = np.nan
            wt = src.window_transform(win) * rasterio.Affine.scale(win.width / ow, win.height / oh)
            part = np.full(shape, np.nan, dtype="float32")
            reproject(arr, part, src_transform=wt, src_crs=src.crs, dst_transform=transform,
                      dst_crs="EPSG:4326", resampling=resampling, src_nodata=np.nan,
                      dst_nodata=np.nan)
            sel = np.isfinite(part)
            out[sel] = part[sel]
        log.info("sampled %s", url.rsplit("/", 1)[-1])
    return out


def jrc_permanent_fraction(transform, shape, threshold: int, rows_per_chunk: int = 4000):
    """Share of 30 m JRC pixels with occurrence >= threshold in each grid cell.

    Read at full resolution in row chunks and block-averaged, because averaging occurrence
    first would erase narrow rivers. Needs the grid to align with the 10-degree tiles
    (true for INDIA_BOUNDS and any resolution that divides 10 degrees into whole JRC pixels).
    """
    out = np.full(shape, np.nan, dtype="float32")
    res = abs(transform.a)
    for url in jrc_tiles():
        try:
            src = rasterio.open(url)
        except RasterioIOError:
            continue
        with src:
            f = int(round(res / abs(src.res[0])))
            col0 = int(round((src.bounds.left - transform.c) / res))
            row0 = int(round((transform.f - src.bounds.top) / res))
            for r in range(0, src.height, rows_per_chunk):
                h = min(rows_per_chunk, src.height - r)
                block = src.read(1, window=rasterio.windows.Window(0, r, src.width, h))
                valid = block != 255
                hit = (block >= threshold) & valid
                hb, wb = h // f, src.width // f
                frac = hit[: hb * f, : wb * f].reshape(hb, f, wb, f).mean(axis=(1, 3))
                seen = valid[: hb * f, : wb * f].reshape(hb, f, wb, f).any(axis=(1, 3))
                frac = np.where(seen, frac, np.nan).astype("float32")
                gr, gc = row0 + r // f, col0
                r_lo, r_hi = max(gr, 0), min(gr + hb, shape[0])
                c_lo, c_hi = max(gc, 0), min(gc + wb, shape[1])
                if r_lo < r_hi and c_lo < c_hi:
                    sub = frac[r_lo - gr : r_hi - gr, c_lo - gc : c_hi - gc]
                    tgt = out[r_lo:r_hi, c_lo:c_hi]
                    np.copyto(tgt, sub, where=np.isfinite(sub))
        log.info("sampled %s", url.rsplit("/", 1)[-1])
    return out


def slope_deg(elev: np.ndarray, transform) -> np.ndarray:
    """Slope on a lat/lon grid using metre spacing that shrinks with latitude."""
    res = abs(transform.a)
    lat = transform.f - res * (np.arange(elev.shape[0]) + 0.5)
    dy = res * 111_320.0
    dx = (res * 111_320.0 * np.cos(np.deg2rad(lat)))[:, None]
    gy, gx = np.gradient(elev, axis=(0, 1))
    return np.degrees(np.arctan(np.hypot(gx / dx, gy / dy)))


def zonal(values: np.ndarray, idx: np.ndarray, area: np.ndarray, n: int) -> np.ndarray:
    """Area-weighted mean of values per district (NaN where nothing valid)."""
    ok = np.isfinite(values) & (idx > 0)
    w = np.bincount(idx[ok], weights=area[ok], minlength=n + 1)[1:]
    s = np.bincount(idx[ok], weights=(values * area)[ok], minlength=n + 1)[1:]
    return np.divide(s, w, out=np.full(n, np.nan), where=w > 0)


def zonal_quantile(values: np.ndarray, idx: np.ndarray, n: int, q: float) -> np.ndarray:
    ok = np.isfinite(values) & (idx > 0)
    s = pd.Series(values[ok]).groupby(idx[ok]).quantile(q)
    out = np.full(n, np.nan)
    out[s.index.to_numpy() - 1] = s.to_numpy()
    return out


def raster_baseline(districts, res: float) -> pd.DataFrame:
    hz = config.load("hazard")["baseline"]
    transform, shape = india_grid(res)
    idx = district_index(districts, transform, shape)
    area = np.broadcast_to(pixel_area_km2(transform, shape[0]), shape)
    n = len(districts)
    out = pd.DataFrame({"district_id": districts.district_id.to_numpy()})

    perm = jrc_permanent_fraction(transform, shape, hz["perm_water_occurrence"])
    out["perm_water_share"] = zonal(np.nan_to_num(perm), idx, area, n)
    del perm

    elev = sample_onto_grid(dem_tiles(), transform, shape)
    out["elev_mean_m"] = zonal(elev, idx, area, n)
    out["slope_mean_deg"] = zonal(slope_deg(elev, transform), idx, area, n)
    low = np.where(np.isfinite(elev), (elev < hz["lowlying_m"]).astype("float32"), np.nan)
    out["lowlying_share"] = zonal(low, idx, area, n)
    p5 = zonal_quantile(elev, idx, n, 0.05)
    rel = np.where(idx > 0, elev - np.r_[np.nan, p5][idx], np.nan)
    out["rel_elev_median_m"] = zonal_quantile(rel, idx, n, 0.5)
    return out


def flood_frequency(flood: pd.DataFrame, hit_share: float) -> pd.DataFrame:
    g = flood[flood.source == "gfd"].groupby("district_id")
    years = (GFD_LAST - GFD_FIRST).days / 365.25
    out = pd.DataFrame({
        "gfd_events_hit": g.flooded_share.apply(lambda s: int((s > hit_share).sum())),
        "gfd_pixel_flood_count": g.flooded_share.sum(),
        "gfd_max_flooded_share": g.flooded_share.max(),
        "gfd_events_mapped": g.size(),
    }).reset_index()
    out["gfd_events_hit_per_decade"] = out.gfd_events_hit / years * 10
    out["gfd_record_years"] = round(years, 2)
    return out


def landfall_frequency(storms: pd.DataFrame, min_grade: str) -> pd.DataFrame:
    from cri.ingest.imd_tracks import grade_rank, load_tracks

    s = storms.dropna(subset=["landfall_district"]).copy()
    tracks = load_tracks()
    # strength at landfall: track wind at the fix nearest the landfall time
    winds = []
    for r in s.itertuples():
        t = tracks[tracks.storm_id == r.storm_id]
        lt = pd.Timestamp(r.landfall_time).tz_localize(None)
        winds.append(float(np.interp(lt.value, t.time.astype("int64"), t.wind_kt)))
    s["wind_at_landfall"] = winds
    from cri.ingest.imd_tracks import grade_from_wind

    s["grade_at_landfall"] = grade_from_wind(s.wind_at_landfall).to_numpy()
    strong = s.grade_at_landfall.map(grade_rank) >= grade_rank(min_grade)
    years = (tracks.time.max() - tracks.time.min()).days / 365.25
    out = pd.DataFrame({
        "landfall_count": s.groupby("landfall_district").size(),
        "landfall_count_strong": s[strong].groupby("landfall_district").size(),
    }).fillna(0).astype(int)
    out.index = out.index.astype(int)
    out.index.name = "district_id"
    out = out.reset_index()
    out["landfall_strong_per_decade"] = out.landfall_count_strong / years * 10
    out["imd_record_years"] = round(years, 2)
    return out


def build(res: float | None = None, with_rasters: bool = True) -> list[Path]:
    hz = config.load("hazard")
    res = res or hz["baseline"]["grid_deg"]
    districts = load_districts()
    out = districts[["district_id"]].copy()
    processed = config.path("processed")

    flood_path = processed / "flood_extent_district_event.parquet"
    if flood_path.exists():
        ff = flood_frequency(pd.read_parquet(flood_path), hz["flood"]["event_hit_share"])
        out = out.merge(ff, on="district_id", how="left")
        fill = ["gfd_events_hit", "gfd_pixel_flood_count", "gfd_events_mapped",
                "gfd_events_hit_per_decade"]
        out[fill] = out[fill].fillna(0)
    storms_path = processed / "cyclone_storms.parquet"
    if storms_path.exists():
        lf = landfall_frequency(pd.read_parquet(storms_path), hz["cyclone"]["min_grade"])
        out = out.merge(lf, on="district_id", how="left")
        fill = ["landfall_count", "landfall_count_strong", "landfall_strong_per_decade"]
        out[fill] = out[fill].fillna(0)
    if with_rasters:
        # the raster part takes a while (about 1 GB of tiles); cache it per grid resolution
        cache = config.path("interim") / f"baseline_rasters_{res:g}.parquet"
        if cache.exists():
            rb = pd.read_parquet(cache)
        else:
            rb = raster_baseline(districts, res)
            cache.parent.mkdir(parents=True, exist_ok=True)
            rb.to_parquet(cache, index=False)
        out = out.merge(rb, on="district_id", how="left")
    out["data_version"] = config.load("project").get("data_version", "dev")
    processed.mkdir(parents=True, exist_ok=True)
    path = processed / OUT_NAME
    out.to_parquet(path, index=False)
    log.info("wrote %s (%d districts, %d columns)", path, len(out), out.shape[1])
    return [path]


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--res", type=float, help="grid resolution in degrees")
    p.add_argument("--no-rasters", action="store_true", help="skip JRC and DEM sampling")
    a = p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("hazard:baseline", ["project", "paths", "hazard"]) as outputs:
        outputs += build(a.res, not a.no_rasters)


if __name__ == "__main__":
    main()
