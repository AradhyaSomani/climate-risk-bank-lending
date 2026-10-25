"""Grid features for the flood susceptibility model (Phase 2B-C).

All features are on the India grid at `grid_deg` (configs/ml/susceptibility.yaml), built from
the same open layers as the Phase 1H baseline:

- `elev_m`, `slope_deg`, `lowlying_share`: Copernicus 90 m DEM, sampled at 0.005 degrees and
  block-averaged (slope is computed before averaging so it is not flattened).
- `rel_elev_m`: cell elevation minus the lowest cell within about 10 km, a proxy for height
  above the nearest drainage.
- `perm_water_share`: JRC Global Surface Water, occurrence at or above the configured level.
- `built_share`, `crop_share`: ESA WorldCover 2021 classes 50 and 40.
- `dist_coast_km`, `dist_river_km`: distance to the Natural Earth 10 m coastline and river
  centrelines (planar distance with a cos(22 N) longitude scale, within 10% across India).

Long-run rainfall and soil are not included: no open, account-free grid was set up for them.
The result is cached in data/interim/susceptibility_features_<res>.npz.

    python -m cri.ml.susceptibility.features
"""

from __future__ import annotations

import argparse
import logging
import math
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from rasterio.features import rasterize
from scipy import ndimage

from cri import config
from cri.hazard import baseline as bl

log = logging.getLogger(__name__)

NE_RIVERS_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_10m_rivers_lake_centerlines.geojson"
)
FINE = 0.005
FEATURES = ["elev_m", "slope_deg", "rel_elev_m", "lowlying_share", "perm_water_share",
            "built_share", "crop_share", "dist_coast_km", "dist_river_km"]


def block_mean(a: np.ndarray, k: int) -> np.ndarray:
    h, w = a.shape[0] // k, a.shape[1] // k
    with np.errstate(invalid="ignore"):
        return np.nanmean(a[: h * k, : w * k].reshape(h, k, w, k), axis=(1, 3))


def fetch_rivers(dest: Path | None = None) -> Path:
    dest = dest or config.path("raw_layers.natural_earth")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "ne_10m_rivers_lake_centerlines.geojson"
    if not out.exists():
        urllib.request.urlretrieve(NE_RIVERS_URL, out)
    return out


def distance_km(mask: np.ndarray, res: float, lat0: float = 22.0) -> np.ndarray:
    """Distance from every cell to the nearest True cell, in km."""
    dy = res * 111.32
    dx = res * 111.32 * math.cos(math.radians(lat0))
    return ndimage.distance_transform_edt(~mask, sampling=(dy, dx)).astype("float32")


def vector_features(transform, shape, res: float) -> dict[str, np.ndarray]:
    from cri.geo.land import fetch as fetch_land

    box = shapely.box(*bl.INDIA_BOUNDS).buffer(2)
    land = gpd.read_file(fetch_land()).clip(box)
    land_r = rasterize(((g, 1) for g in land.geometry), out_shape=shape, transform=transform,
                       fill=0, dtype="uint8").astype(bool)
    rivers = gpd.read_file(fetch_rivers()).clip(box)
    river_r = rasterize(((g, 1) for g in rivers.geometry), out_shape=shape, transform=transform,
                        fill=0, dtype="uint8", all_touched=True).astype(bool)
    return {"dist_coast_km": distance_km(~land_r, res), "dist_river_km": distance_km(river_r, res)}


def build(res: float | None = None, refresh: bool = False) -> Path:
    cfg = config.load("ml/susceptibility")
    hz = config.load("hazard")["baseline"]
    res = res or float(cfg["grid_deg"])
    out = config.path("interim") / f"susceptibility_features_{res:g}.npz"
    if out.exists() and not refresh:
        return out
    k = int(round(res / FINE))
    t_fine, s_fine = bl.india_grid(FINE)
    t, shape = bl.india_grid(res)
    feats: dict[str, np.ndarray] = {}

    elev = bl.sample_onto_grid(bl.dem_tiles(), t_fine, s_fine)
    feats["slope_deg"] = block_mean(bl.slope_deg(elev, t_fine), k)
    low = np.where(np.isfinite(elev), (elev < hz["lowlying_m"]).astype("float32"), np.nan)
    feats["lowlying_share"] = block_mean(low, k)
    del low
    feats["elev_m"] = block_mean(elev, k)
    del elev
    e = feats["elev_m"]
    win = max(3, int(round(0.1 / res)) | 1)  # odd window of about 10 km
    local_min = ndimage.minimum_filter(np.where(np.isfinite(e), e, np.inf), size=win)
    feats["rel_elev_m"] = np.where(np.isfinite(e), e - local_min, np.nan).astype("float32")

    from cri.hazard.landcover import worldcover_on_grid

    wc = worldcover_on_grid(t_fine, s_fine)
    seen = wc > 0
    for cls, name in ((50, "built_share"), (40, "crop_share")):
        feats[name] = block_mean(np.where(seen, (wc == cls).astype("float32"), np.nan), k)
    del wc, seen

    feats["perm_water_share"] = bl.jrc_permanent_fraction(t, shape, hz["perm_water_occurrence"])
    feats.update(vector_features(t, shape, res))
    feats = {n: feats[n][: shape[0], : shape[1]].astype("float32") for n in FEATURES}
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, res=res, **feats)
    log.info("wrote %s", out)
    return out


def load(res: float | None = None) -> dict[str, np.ndarray]:
    res = res or float(config.load("ml/susceptibility")["grid_deg"])
    f = np.load(config.path("interim") / f"susceptibility_features_{res:g}.npz")
    return {n: f[n] for n in FEATURES}


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args(argv)
    runlog.setup_logging()
    print(build(refresh=a.refresh))


if __name__ == "__main__":
    main()
