"""Per-district flood statistics for one flood event raster (Phase 1E).

Input: a Global Flood Database event GeoTIFF (bands flooded, duration, clear_views,
clear_perc, jrc_perm_water) or any raster with the same band names, plus district polygons.
Output: one row per district that the raster covers, with the columns of contract C3
`flood_extent_district_event`.

Areas use the exact area of each latitude-longitude pixel on the sphere, so no projection
is needed and the 250 m grid is handled correctly at every latitude.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

from cri import config

log = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0072  # authalic radius
BUILT, CROP = 50, 40


def pixel_area_km2(transform, height: int) -> np.ndarray:
    """Area of each row's pixels (km2) for a north-up lat/lon grid; shape (height, 1)."""
    top = transform.f
    dlat = transform.e  # negative for north-up
    dlon = np.deg2rad(abs(transform.a))
    lat_top = np.deg2rad(top + dlat * np.arange(height))
    lat_bot = np.deg2rad(top + dlat * (np.arange(height) + 1))
    rows = EARTH_RADIUS_KM**2 * dlon * np.abs(np.sin(lat_top) - np.sin(lat_bot))
    return rows[:, None]


def _ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """num / den, NaN where den is 0."""
    return np.divide(num, den, out=np.full_like(num, np.nan, dtype=float), where=den > 0)


def district_index(districts: gpd.GeoDataFrame, transform, shape) -> np.ndarray:
    """Raster of 1-based row positions into `districts` (0 = no district)."""
    shapes = ((geom, i + 1) for i, geom in enumerate(districts.geometry))
    return rasterize(shapes, out_shape=shape, transform=transform, fill=0, dtype="int32")


def flood_stats(
    bands: dict[str, np.ndarray],
    transform,
    districts: gpd.GeoDataFrame,
    landcover: np.ndarray | None = None,
    mask_permanent_water: bool = True,
    min_clear_perc: float = 0.0,
) -> pd.DataFrame:
    """District statistics from in-memory bands on one grid."""
    flooded = bands["flooded"]
    shape = flooded.shape
    idx = district_index(districts, transform, shape)
    area = np.broadcast_to(pixel_area_km2(transform, shape[0]), shape)
    n = len(districts) + 1

    valid = np.isfinite(flooded)
    wet = valid & (flooded > 0.5)
    if mask_permanent_water and "jrc_perm_water" in bands:
        wet &= ~(bands["jrc_perm_water"] > 0.5)
    clear = None
    if "clear_perc" in bands:
        clear = np.nan_to_num(bands["clear_perc"])
        if clear.max() > 1.0:  # catalog documents 0-100; the bucket rasters store 0-1
            clear = clear / 100.0
    if min_clear_perc > 0 and clear is not None:
        wet &= clear >= min_clear_perc

    def total(weights: np.ndarray) -> np.ndarray:
        return np.bincount(idx.ravel(), weights=weights.ravel(), minlength=n)[1:]

    mapped_km2 = total(np.where(valid, area, 0.0))
    flooded_km2 = total(np.where(wet, area, 0.0))

    out = pd.DataFrame(
        {
            "district_id": districts["district_id"].to_numpy(),
            "flooded_km2": flooded_km2,
            "mapped_km2": mapped_km2,
        }
    )
    district_km2 = districts["area_km2"].to_numpy()
    out["flooded_share"] = np.clip(flooded_km2 / district_km2, 0, 1)
    out["mapped_share"] = np.clip(mapped_km2 / district_km2, 0, 1)

    if "duration" in bands:
        dur = np.nan_to_num(bands["duration"])
        out["duration_days"] = _ratio(total(np.where(wet, area * dur, 0.0)), flooded_km2)
    else:
        out["duration_days"] = np.nan
    if clear is not None:
        out["clear_view_share"] = _ratio(total(np.where(valid, area * clear, 0.0)), mapped_km2)
    else:
        out["clear_view_share"] = np.nan

    for cls, col in ((BUILT, "flooded_built_share"), (CROP, "flooded_crop_share")):
        if landcover is None:
            out[col] = np.nan
            continue
        is_cls = landcover == cls
        cls_km2 = total(np.where(valid & is_cls, area, 0.0))
        wet_cls = total(np.where(wet & is_cls, area, 0.0))
        out[col] = _ratio(wet_cls, cls_km2)

    return out[out["mapped_km2"] > 0].drop(columns="mapped_km2").reset_index(drop=True)


def read_bands(path: Path, bounds=None) -> tuple[dict[str, np.ndarray], object]:
    """Read every named band of a GFD-style raster, optionally cropped to bounds."""
    with rasterio.open(path) as src:
        window = None
        transform = src.transform
        if bounds is not None:
            window = rasterio.windows.from_bounds(*bounds, transform=src.transform)
            window = window.round_offsets().round_lengths().intersection(
                rasterio.windows.Window(0, 0, src.width, src.height)
            )
            transform = src.window_transform(window)
        names = src.descriptions
        bands = {
            (names[i] or f"b{i + 1}"): src.read(i + 1, window=window).astype("float32")
            for i in range(src.count)
        }
    return bands, transform


def event_flood_extent(
    raster: Path,
    districts: gpd.GeoDataFrame,
    event_id: str,
    source: str = "gfd",
    with_landcover: bool = True,
) -> pd.DataFrame:
    """C3 rows for one event raster, restricted to districts that overlap the raster."""
    hz = config.load("hazard")["flood"]
    with rasterio.open(raster) as src:
        rb = src.bounds
    d = districts.cx[rb.left : rb.right, rb.bottom : rb.top]
    if d.empty:
        return pd.DataFrame()
    minx, miny, maxx, maxy = d.total_bounds
    bounds = (max(minx, rb.left), max(miny, rb.bottom), min(maxx, rb.right), min(maxy, rb.top))
    bands, transform = read_bands(raster, bounds)
    landcover = None
    if with_landcover:
        from cri.hazard.landcover import worldcover_on_grid

        landcover = worldcover_on_grid(transform, bands["flooded"].shape)
    stats = flood_stats(
        bands, transform, d.reset_index(drop=True), landcover,
        mask_permanent_water=hz["mask_permanent_water"], min_clear_perc=hz["min_clear_perc"],
    )
    stats.insert(0, "event_id", event_id)
    stats.insert(2, "source", source)
    stats["data_version"] = config.load("project").get("data_version", "dev")
    return stats
