"""ESA WorldCover 2021 classes resampled onto another raster grid.

WorldCover is 10 m in 3x3 degree COG tiles on AWS open data. For a 250 m flood grid we read
each tile at a decimated resolution (GDAL picks the internal overview) and then place it on
the target grid with nearest-neighbour resampling. At district level the class shares from
these samples match the full-resolution shares closely; they are not exact pixel counts.
"""

from __future__ import annotations

import math
import os

import numpy as np
import rasterio
from rasterio.errors import RasterioIOError
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds

TILE_URL = (
    "/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
)
BUILT, CROP, PERMANENT_WATER = 50, 40, 80

# GDAL's curl needs the proxy's CA bundle in this environment; harmless elsewhere.
if os.path.exists("/root/.ccr/ca-bundle.crt"):
    os.environ.setdefault("CURL_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")


def tile_name(lat0: int, lon0: int) -> str:
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    return f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"


def tiles_for_bounds(left: float, bottom: float, right: float, top: float) -> list[str]:
    lats = range(3 * math.floor(bottom / 3), 3 * math.ceil(top / 3), 3)
    lons = range(3 * math.floor(left / 3), 3 * math.ceil(right / 3), 3)
    return [tile_name(la, lo) for la in lats for lo in lons]


def worldcover_on_grid(transform, shape: tuple[int, int], crs="EPSG:4326") -> np.ndarray:
    """WorldCover class codes on the given grid (0 where no tile exists, e.g. open sea)."""
    height, width = shape
    left, top = transform.c, transform.f
    right, bottom = left + transform.a * width, top + transform.e * height
    out = np.zeros(shape, dtype=np.uint8)
    target_res = abs(transform.a)
    for tile in tiles_for_bounds(left, bottom, right, top):
        try:
            src = rasterio.open(TILE_URL.format(tile=tile))
        except RasterioIOError:
            continue  # no tile: ocean or outside coverage
        with src:
            b = src.bounds
            ib = (max(left, b.left), max(bottom, b.bottom), min(right, b.right), min(top, b.top))
            if ib[0] >= ib[2] or ib[1] >= ib[3]:
                continue
            win = from_bounds(*ib, transform=src.transform)
            factor = max(1, int(target_res / abs(src.res[0]) / 2))  # keep 2x oversampling
            oh = max(1, int(win.height / factor))
            ow = max(1, int(win.width / factor))
            arr = src.read(1, window=win, out_shape=(oh, ow), resampling=Resampling.nearest)
            wt = src.window_transform(win) * rasterio.Affine.scale(win.width / ow, win.height / oh)
            part = np.zeros(shape, dtype=np.uint8)
            reproject(
                arr, part, src_transform=wt, src_crs=src.crs, dst_transform=transform,
                dst_crs=crs, resampling=Resampling.mode, src_nodata=0, dst_nodata=0,
            )
            out = np.where(part > 0, part, out)
    return out
