"""Baselines the U-Net must beat, and the pixel metrics shared with it (Phase 2B-B).

- Otsu: one threshold per chip on VV or VH backscatter (dB); water is below it. Standard
  practice for SAR flood mapping and the rule behind `cri.ingest.sentinel1`.
- Fixed threshold: one VH (or VV) threshold for every scene, chosen to maximise water IoU on
  the training events. Harder to beat than per-chip Otsu, which fails on chips with little
  water (no second mode in the histogram).
- Change detection: water where backscatter dropped by more than `drop_db` from a pre-event
  scene and is below a water threshold. Sen1Floods11 ships no pre-event scene, so this one
  runs only on scenes exported from Earth Engine (`cri.ingest.sentinel1`).

Metrics pool the confusion counts over every valid pixel of an event, then average events
equally, so a large event does not drown out a small one.

    python -m cri.ml.flood_cnn.baselines     # baseline scores per event on the test split
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

from cri import config

log = logging.getLogger(__name__)


def otsu_threshold(values: np.ndarray, bins: int = 256) -> float:
    v = values[np.isfinite(values)]
    if v.size == 0 or v.min() == v.max():
        return float("nan")
    hist, edges = np.histogram(v, bins=bins)
    mids = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * mids) / np.maximum(w0, 1)
    m1 = (np.sum(hist * mids) - np.cumsum(hist * mids)) / np.maximum(w1, 1)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(mids[np.argmax(between[:-1])])


def otsu_water(db: np.ndarray) -> np.ndarray:
    """Water mask from one backscatter band in dB (NaN = no data -> not water)."""
    t = otsu_threshold(db)
    if not np.isfinite(t):
        return np.zeros(db.shape, dtype=bool)
    return np.nan_to_num(db, nan=np.inf) < t


def change_detection(pre_db: np.ndarray, post_db: np.ndarray, drop_db: float = 3.0,
                     water_db: float | None = None) -> np.ndarray:
    """New water: a drop of more than `drop_db` and post-event backscatter below the water
    threshold (Otsu on the post scene unless `water_db` is given)."""
    thr = water_db if water_db is not None else otsu_threshold(post_db)
    with np.errstate(invalid="ignore"):
        return ((post_db - pre_db) < -drop_db) & (post_db < thr)


def confusion(pred: np.ndarray, label: np.ndarray) -> dict[str, int]:
    v = label >= 0
    p, t = pred[v].astype(bool), label[v] == 1
    return {"tp": int((p & t).sum()), "fp": int((p & ~t).sum()),
            "fn": int((~p & t).sum()), "tn": int((~p & ~t).sum())}


def scores(c: dict[str, int]) -> dict[str, float]:
    tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
    iou = tp / (tp + fp + fn) if tp + fp + fn else np.nan
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else np.nan
    acc = (tp + tn) / (tp + fp + fn + tn) if tp + fp + fn + tn else np.nan
    return {"iou_water": iou, "f1_water": f1, "accuracy": acc}


def by_event(rows: pd.DataFrame) -> pd.DataFrame:
    """Rows of (event, tp, fp, fn, tn) per chip or patch -> scores per event plus the mean."""
    g = rows.groupby("event")[["tp", "fp", "fn", "tn"]].sum()
    out = pd.DataFrame([{"event": e, **scores(r.to_dict())} for e, r in g.iterrows()])
    mean = out[["iou_water", "f1_water", "accuracy"]].mean().to_dict()
    return pd.concat([out, pd.DataFrame([{"event": "mean", **mean}])], ignore_index=True)


def fit_fixed_threshold(chip_ids: list[str], band: int = 1, root=None,
                        grid: np.ndarray | None = None) -> float:
    """Single dB threshold (band 0 = VV, 1 = VH) maximising pooled water IoU."""
    from cri.ml.flood_cnn.data import load_chip

    grid = np.arange(-30.0, -5.0, 0.25) if grid is None else grid
    tot = np.zeros((len(grid), 3))  # tp, fp, fn per candidate threshold
    for chip in chip_ids:
        _, y, db = load_chip(chip, ["vv"], root)
        v = y >= 0
        x, t = db[band][v], y[v] == 1
        x = np.nan_to_num(x, nan=np.inf)
        for i, g in enumerate(grid):
            p = x < g
            tot[i] += [(p & t).sum(), (p & ~t).sum(), (~p & t).sum()]
    iou = tot[:, 0] / np.maximum(tot.sum(axis=1), 1)
    return float(grid[int(np.argmax(iou))])


def baseline_scores(chip_ids: list[str], fixed: dict[str, float] | None = None,
                    root=None) -> pd.DataFrame:
    """Per-event scores of Otsu on VV and VH, and of fixed thresholds if given
    ({"fixed_vh": -18.5, ...})."""
    from cri.ingest.sen1floods11 import chip_event
    from cri.ml.flood_cnn.data import load_chip

    rows = []
    for chip in chip_ids:
        _, y, db = load_chip(chip, ["vv"], root)
        preds = {"otsu_vv": otsu_water(db[0]), "otsu_vh": otsu_water(db[1])}
        for name, thr in (fixed or {}).items():
            preds[name] = np.nan_to_num(db[1 if name.endswith("vh") else 0], nan=np.inf) < thr
        for name, pred in preds.items():
            rows.append({"method": name, "chip": chip, "event": chip_event(chip),
                         **confusion(pred, y)})
    rows = pd.DataFrame(rows)
    return pd.concat([by_event(g).assign(method=m) for m, g in rows.groupby("method")],
                     ignore_index=True)


def chance_scores(chip_ids: list[str], root=None) -> pd.DataFrame:
    """Per-event scores of calling every valid pixel water. A model with no skill scores at
    most this water IoU (it equals the event's water share), so it is the chance level for
    the shuffled-label check."""
    from cri.ingest.sen1floods11 import chip_event
    from cri.ml.flood_cnn.data import load_chip

    rows = []
    for chip in chip_ids:
        _, y, _ = load_chip(chip, ["vv"], root)
        rows.append({"chip": chip, "event": chip_event(chip),
                     **confusion(np.ones(y.shape, dtype=bool), y)})
    return by_event(pd.DataFrame(rows)).assign(method="all_water")


def main(argv: list[str] | None = None) -> None:
    from cri import runlog
    from cri.ml.flood_cnn.data import chips, split_chips

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--split", default="test", choices=["train", "val", "test"])
    a = p.parse_args(argv)
    runlog.setup_logging()
    cfg = config.load("ml/flood_cnn")["data"]
    parts = split_chips(chips(), cfg["test_events"], cfg["val_events"])
    fixed = {f"fixed_{b}": fit_fixed_threshold(parts["train"], i) for i, b in
             enumerate(["vv", "vh"])}
    print("fixed thresholds fitted on train (dB):", fixed)
    print(baseline_scores(parts[a.split], fixed).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
