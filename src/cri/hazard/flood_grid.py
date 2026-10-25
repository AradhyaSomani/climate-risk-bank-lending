"""Global Flood Database events on a coarse India grid (input to Phase 2B-C).

For each event, the share of every grid cell that the event raster observed and the share
that was flooded (permanent water removed), on the regular India grid from
`cri.hazard.baseline.india_grid`. Per-event grids are cached in data/interim/gfd_grid/, so
the event rasters can be deleted after one pass. `cri.hazard.flood_extent.build_gfd` writes
the grid for every event it processes; this module fills in the rest.

    python -m cri.hazard.flood_grid      # all India events, grid from configs/ml
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from cri import config
from cri.hazard.baseline import INDIA_BOUNDS, india_grid
from cri.hazard.zonal_stats import read_bands

log = logging.getLogger(__name__)


def grid_res() -> float:
    return float(config.load("ml/susceptibility")["grid_deg"])


def cache_dir(res: float) -> Path:
    return config.path("interim") / f"gfd_grid_{res:g}"


def event_grid(tif: Path, res: float, mask_perm: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """(flooded share, observed share) of each India grid cell for one event raster."""
    transform, shape = india_grid(res)
    with rasterio.open(tif) as src:
        rb = src.bounds
    left, bottom, right, top = INDIA_BOUNDS
    bounds = (max(left, rb.left), max(bottom, rb.bottom), min(right, rb.right), min(top, rb.top))
    wet_g = np.zeros(shape, dtype="float32")
    obs_g = np.zeros(shape, dtype="float32")
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        return wet_g, obs_g
    bands, src_t = read_bands(tif, bounds)
    flooded = bands["flooded"]
    valid = np.isfinite(flooded)
    wet = valid & (flooded > 0.5)
    if mask_perm and "jrc_perm_water" in bands:
        wet &= ~(bands["jrc_perm_water"] > 0.5)
    for arr, out in ((wet, wet_g), (valid, obs_g)):
        reproject(arr.astype("float32"), out, src_transform=src_t, src_crs="EPSG:4326",
                  dst_transform=transform, dst_crs="EPSG:4326", resampling=Resampling.average)
    return wet_g, obs_g


def save_event(event_id: str, tif: Path, res: float | None = None) -> Path:
    res = res or grid_res()
    out = cache_dir(res) / f"{event_id}.npz"
    if not out.exists():
        wet, obs = event_grid(tif, res, config.load("hazard")["flood"]["mask_permanent_water"])
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out, wet=wet.astype("float16"), obs=obs.astype("float16"))
    return out


def build(ids: list[int] | None = None, res: float | None = None,
          keep_rasters: bool = False) -> Path:
    """Fetch missing events, then write the stack summary: per cell, events observed,
    events flooded above `min_share`, and the largest flooded share."""
    from cri.hazard.flood_extent import gfd_event_id
    from cri.ingest.gfd import fetch_event

    res = res or grid_res()
    min_share = float(config.load("ml/susceptibility").get("target_min_share", 0.05))
    index = pd.read_csv(config.path("events") / "gfd_india_events.csv")
    if ids:
        index = index[index.dfo_id.isin(ids)]
    raw = config.path("raw_layers.gfd")
    _, shape = india_grid(res)
    n_obs = np.zeros(shape, dtype="int16")
    n_hit = np.zeros(shape, dtype="int16")
    max_share = np.zeros(shape, dtype="float32")
    for i, ev in enumerate(index.itertuples(), 1):
        eid = gfd_event_id(ev.dfo_id)
        f = cache_dir(res) / f"{eid}.npz"
        if not f.exists():
            log.info("[%d/%d] %s", i, len(index), eid)
            tif = fetch_event(int(ev.dfo_id), raw, index)
            save_event(eid, tif, res)
            if not keep_rasters:
                shutil.rmtree(tif.parent)
        g = np.load(f)
        wet, obs = g["wet"].astype("float32"), g["obs"].astype("float32")
        n_obs += obs > 0.5
        n_hit += wet >= min_share
        np.maximum(max_share, wet, out=max_share)
    out = config.path("interim") / f"gfd_grid_summary_{res:g}.npz"
    np.savez_compressed(out, n_obs=n_obs, n_hit=n_hit, max_share=max_share,
                        n_events=len(index), res=res)
    log.info("wrote %s (%d events)", out, len(index))
    return out


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--ids", type=int, nargs="*")
    p.add_argument("--keep-rasters", action="store_true")
    a = p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("hazard:flood_grid", ["paths", "hazard", "ml/susceptibility"]) as outputs:
        outputs.append(build(a.ids, keep_rasters=a.keep_rasters))


if __name__ == "__main__":
    main()
