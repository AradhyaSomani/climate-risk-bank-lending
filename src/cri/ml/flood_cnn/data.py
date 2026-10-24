"""Sen1Floods11 patches and event-level splits for the U-Net (Phase 2B-B).

Each 512x512 chip is cut into fixed patches. Splits are by flood event, never by random
patch: the test events (India and Bolivia by default) contribute no patch to training or
validation, so a test score measures transfer to an unseen flood. Labels are -1 (no data,
ignored by the loss and the metrics), 0 (dry) and 1 (water).

Channels: `vv`, `vh` (dB, clipped and scaled to 0-1), and optionally `dem` and `slope` from
the Copernicus 90 m DEM resampled onto the chip, for the SAR-plus-terrain ablation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling

from cri import config
from cri.ingest.sen1floods11 import chip_event, chip_id

log = logging.getLogger(__name__)

DB_RANGE = {"vv": (-30.0, 0.0), "vh": (-40.0, -5.0)}
CHANNELS = ["vv", "vh", "dem", "slope"]


@dataclass
class Split:
    x: np.ndarray        # (n, channels, patch, patch) float32
    y: np.ndarray        # (n, patch, patch) int8: -1, 0, 1
    meta: pd.DataFrame   # chip, event, row, col per patch


def chips(root: Path | None = None) -> pd.DataFrame:
    root = root or config.path("raw_layers.s1_labels")
    files = sorted((root / "S1Hand").glob("*_S1Hand.tif"))
    return pd.DataFrame({"chip": [chip_id(f.name) for f in files],
                         "event": [chip_event(f.name) for f in files]})


def split_chips(chip_table: pd.DataFrame, test_events: list[str],
                val_events: list[str]) -> dict[str, list[str]]:
    overlap = set(test_events) & set(val_events)
    if overlap:
        raise ValueError(f"events in both test and validation: {overlap}")
    ev = chip_table.event
    test = ev.isin(test_events)
    val = ev.isin(val_events)
    return {"train": chip_table.chip[~test & ~val].tolist(),
            "val": chip_table.chip[val].tolist(),
            "test": chip_table.chip[test].tolist()}


def scale_db(x: np.ndarray, band: str) -> np.ndarray:
    lo, hi = DB_RANGE[band]
    return ((np.clip(x, lo, hi) - lo) / (hi - lo)).astype("float32")


def terrain(transform, shape) -> tuple[np.ndarray, np.ndarray]:
    """DEM (m) and slope (degrees) on the chip grid."""
    from cri.hazard.baseline import dem_tiles, sample_onto_grid, slope_deg

    h, w = shape
    left, top = transform.c, transform.f
    bounds = (left, top + transform.e * h, left + transform.a * w, top)
    elev = sample_onto_grid(dem_tiles(bounds), transform, shape,
                            resampling=Resampling.bilinear)
    return elev, slope_deg(elev, transform)


def load_chip(chip: str, channels: list[str], root: Path | None = None,
              cache: Path | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(channels x H x W) inputs, the label, and the raw dB stack for the baselines."""
    root = root or config.path("raw_layers.s1_labels")
    with rasterio.open(root / "S1Hand" / f"{chip}_S1Hand.tif") as r:
        db = r.read().astype("float32")  # VV, VH
        transform, shape = r.transform, (r.height, r.width)
    with rasterio.open(root / "LabelHand" / f"{chip}_LabelHand.tif") as r:
        y = r.read(1).astype("int8")
    y[~np.isfinite(db).all(axis=0)] = -1
    bands = {"vv": scale_db(np.nan_to_num(db[0], nan=-30.0), "vv"),
             "vh": scale_db(np.nan_to_num(db[1], nan=-40.0), "vh")}
    if {"dem", "slope"} & set(channels):
        cache = cache or config.path("interim") / "s1_terrain"
        f = cache / f"{chip}.npz"
        if f.exists():
            t = np.load(f)
            elev, slope = t["elev"], t["slope"]
        else:
            elev, slope = terrain(transform, shape)
            cache.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(f, elev=elev, slope=slope)
        bands["dem"] = (np.clip(np.nan_to_num(elev), 0, 3000) / 3000).astype("float32")
        bands["slope"] = (np.clip(np.nan_to_num(slope), 0, 45) / 45).astype("float32")
    return np.stack([bands[c] for c in channels]), y, db


def to_patches(x: np.ndarray, y: np.ndarray, size: int):
    _, h, w = x.shape
    for r in range(0, h - size + 1, size):
        for c in range(0, w - size + 1, size):
            yield r, c, x[:, r:r + size, c:c + size], y[r:r + size, c:c + size]


def build_split(chip_ids: list[str], channels: list[str], patch: int, min_valid: float,
                root: Path | None = None) -> Split:
    xs, ys, meta = [], [], []
    for chip in chip_ids:
        x, y, _ = load_chip(chip, channels, root)
        for r, c, px, py in to_patches(x, y, patch):
            if (py >= 0).mean() < min_valid:
                continue
            xs.append(px)
            ys.append(py)
            meta.append({"chip": chip, "event": chip_event(chip), "row": r, "col": c})
    n_ch = len(channels)
    return Split(np.stack(xs) if xs else np.zeros((0, n_ch, patch, patch), "float32"),
                 np.stack(ys) if ys else np.zeros((0, patch, patch), "int8"),
                 pd.DataFrame(meta, columns=["chip", "event", "row", "col"]))


def load_splits(cfg: dict | None = None, root: Path | None = None) -> dict[str, Split]:
    cfg = cfg or config.load("ml/flood_cnn")["data"]
    parts = split_chips(chips(root), cfg["test_events"], cfg["val_events"])
    out = {}
    for name, ids in parts.items():
        out[name] = build_split(ids, cfg["channels"], cfg["patch"], cfg["min_valid_share"], root)
        log.info("%s: %d chips, %d patches, events %s", name, len(ids), len(out[name].y),
                 sorted(out[name].meta.event.unique()))
    return out
