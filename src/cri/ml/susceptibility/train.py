"""Flood susceptibility with gradient boosting and spatial block cross-validation (Phase 2B-C).

The question: can terrain and land cover tell where floods happen, for places whose flood
record is short or empty? The target is weak by construction, because the Global Flood
Database covers 2000-2018 only and misses short and urban floods.

Two tests, both scored only on cells in held-out spatial blocks (never random cells):

1. Static: target = cell flooded in at least one GFD event. Gradient boosting against a
   logistic regression on the same features.
2. Gate: target = cell flooded in an event from the cut-off year on (configs/hazard.yaml
   `validation.flood_cutoff_year`), among cells those events observed. The baseline is the
   raw flood-event count before the cut-off, which needs no training. The model sees no
   flood history at all (terrain and land cover only); a second variant also gets the
   earlier count, to show whether the features add anything to the record.

The per-district susceptibility score is the mean predicted probability over a district's
cells from a model fitted on every event. It is used in the Phase 2 composite only if the
gate passes.

    python -m cri.ml.susceptibility.train
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from cri import config
from cri.hazard.baseline import india_grid
from cri.hazard.flood_grid import cache_dir
from cri.hazard.validation import auc
from cri.ml import tracking
from cri.ml.susceptibility import features as feat

log = logging.getLogger(__name__)

OUT_NAME = "susceptibility_district.parquet"


def event_stack(res: float, cutoff: int, min_share: float) -> dict[str, np.ndarray]:
    """Per cell: events observed and events flooded, before and from the cut-off year."""
    from cri.hazard.indicators import event_years

    files = sorted(cache_dir(res).glob("GFD-*.npz"))
    years = event_years([f.stem for f in files])
    _, shape = india_grid(res)
    out = {k: np.zeros(shape, dtype="int16") for k in
           ("obs_pre", "hit_pre", "obs_post", "hit_post")}
    for f in files:
        g = np.load(f)
        wet, obs = g["wet"].astype("float32"), g["obs"].astype("float32")
        tag = "post" if years[f.stem] >= cutoff else "pre"
        out[f"obs_{tag}"] += obs > 0.5
        out[f"hit_{tag}"] += wet >= min_share
    out["n_events"] = np.array(len(files))
    return out


def blocks(shape, res: float, block_deg: float) -> np.ndarray:
    t, _ = india_grid(res)
    rows, cols = np.indices(shape)
    lon = t.c + (cols + 0.5) * res
    lat = t.f - (rows + 0.5) * res
    return (np.floor(lon / block_deg) * 1000 + np.floor(lat / block_deg)).astype(int)


def lgbm(cfg: dict, seed: int):
    import lightgbm as lgb

    m = cfg["model"]
    return lgb.LGBMClassifier(learning_rate=m["learning_rate"], n_estimators=m["n_estimators"],
                              num_leaves=m["num_leaves"], min_child_samples=m["min_child_samples"],
                              subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                              random_state=seed, n_jobs=m.get("n_jobs", 2), verbose=-1)


def logistic():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=500))


def oof(model_fn, x: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int) -> np.ndarray:
    """Out-of-fold probabilities with spatial blocks as groups."""
    pred = np.full(len(y), np.nan)
    for tr, te in GroupKFold(folds).split(x, y, groups):
        m = model_fn()
        m.fit(x[tr], y[tr])
        pred[te] = m.predict_proba(x[te])[:, 1]
    return pred


def subsample(mask: np.ndarray, max_cells: int | None, seed: int) -> np.ndarray:
    """At most `max_cells` of the cells in `mask`, drawn at random (blocks stay intact as
    CV groups, they only get thinner)."""
    if not max_cells or mask.sum() <= max_cells:
        return mask
    idx = np.flatnonzero(mask)
    keep = np.random.default_rng(seed).choice(idx, max_cells, replace=False)
    out = np.zeros_like(mask)
    out[keep] = True
    return out


def fill(x: np.ndarray) -> np.ndarray:
    """Logistic regression cannot take NaN: median-fill per column (boosting handles NaN)."""
    x = x.copy()
    med = np.nanmedian(x, axis=0)
    idx = np.where(np.isnan(x))
    x[idx] = np.take(med, idx[1])
    return x


def fit_and_score(cfg: dict | None = None, processed: Path | None = None) -> dict:
    from cri.geo.districts import load_districts
    from cri.hazard.zonal_stats import district_index

    cfg = cfg or config.load("ml/susceptibility")
    res = float(cfg["grid_deg"])
    cutoff = config.load("hazard")["validation"]["flood_cutoff_year"]
    seed, folds = cfg["cv"]["seed"], cfg["cv"]["folds"]
    f = feat.load(res)
    ev = event_stack(res, cutoff, float(cfg.get("target_min_share", 0.05)))
    t, shape = india_grid(res)
    districts = load_districts()
    didx = district_index(districts, t, shape)
    grp = blocks(shape, res, cfg["cv"]["block_deg"])
    names = [n for n in cfg["features"] if n in f]
    x_all = np.stack([f[n].ravel() for n in names], axis=1)

    inside = didx.ravel() > 0
    obs_any = (ev["obs_pre"] + ev["obs_post"]).ravel() > 0
    hit_any = (ev["hit_pre"] + ev["hit_post"]).ravel() > 0
    results = {"features": names, "n_events": int(ev["n_events"]), "cutoff": cutoff}

    # 1. static target, block CV
    max_cells = cfg["cv"].get("max_cells")
    s = subsample(inside & obs_any, max_cells, seed)
    log.info("static: %d cells", s.sum())
    xs, ys, gs = x_all[s], hit_any[s].astype(int), grp.ravel()[s]
    p_gb = oof(lambda: lgbm(cfg, seed), xs, ys, gs, folds)
    p_lr = oof(logistic, fill(xs), ys, gs, folds)
    results["static"] = {"cells": int(s.sum()), "positive_rate": float(ys.mean()),
                         "auc_lgbm": auc(pd.Series(p_gb), pd.Series(ys.astype(bool))),
                         "auc_logistic": auc(pd.Series(p_lr), pd.Series(ys.astype(bool)))}

    # 2. gate: later floods, terrain only, against the earlier count
    log.info("static AUC lgbm %.3f, logistic %.3f", results["static"]["auc_lgbm"],
             results["static"]["auc_logistic"])
    g = subsample(inside & (ev["obs_post"].ravel() > 0), max_cells, seed + 1)
    log.info("gate: %d cells", g.sum())
    yg = (ev["hit_post"].ravel()[g] > 0).astype(int)
    count_pre = ev["hit_pre"].ravel()[g].astype(float)
    xg, gg = x_all[g], grp.ravel()[g]
    p_terrain = oof(lambda: lgbm(cfg, seed), xg, yg, gg, folds)
    p_with_count = oof(lambda: lgbm(cfg, seed), np.c_[xg, count_pre], yg, gg, folds)
    p_lr_g = oof(logistic, fill(xg), yg, gg, folds)
    # leakage check: the same pipeline on shuffled labels must score about 0.5
    y_shuf = np.random.default_rng(seed).permutation(yg)
    p_shuf = oof(lambda: lgbm(cfg, seed), xg, y_shuf, gg, folds)
    lab = pd.Series(yg.astype(bool))
    results["gate"] = {
        "cells": int(g.sum()), "positive_rate": float(yg.mean()),
        "auc_count_before": auc(pd.Series(count_pre), lab),
        "auc_lgbm_terrain": auc(pd.Series(p_terrain), lab),
        "auc_lgbm_terrain_plus_count": auc(pd.Series(p_with_count), lab),
        "auc_logistic_terrain": auc(pd.Series(p_lr_g), lab),
        "auc_lgbm_shuffled_labels": auc(pd.Series(p_shuf), pd.Series(y_shuf.astype(bool))),
    }

    # district level: rank correlation with later flooded share of cells
    dist_g = didx.ravel()[g]
    d = pd.DataFrame({"d": dist_g, "y": yg, "count": count_pre, "p": p_terrain,
                      "pc": p_with_count}).groupby("d").mean()
    d = d[d.index > 0]
    results["district"] = {
        "districts": len(d),
        "spearman_count_before": float(spearmanr(d["count"], d.y).statistic),
        "spearman_lgbm_terrain": float(spearmanr(d.p, d.y).statistic),
        "spearman_lgbm_terrain_plus_count": float(spearmanr(d.pc, d.y).statistic),
    }

    log.info("gate %s", results["gate"])
    # full-period model for the district score (terrain only), scored on every cell
    m = lgbm(cfg, seed).fit(xs, ys)
    prob = np.full(inside.shape, np.nan)
    prob[inside] = m.predict_proba(x_all[inside])[:, 1]
    imp = pd.Series(m.booster_.feature_importance("gain"), index=names)
    results["importance_gain"] = (imp / imp.sum()).round(3).to_dict()
    dd = pd.DataFrame({"district_id": districts.district_id.to_numpy()[didx.ravel()[inside] - 1],
                       "p": prob[inside]})
    dist = dd.groupby("district_id").p.mean().rename("susceptibility").reset_index()
    dist["data_version"] = config.load("project").get("data_version", "dev")
    processed = processed or config.path("processed")
    processed.mkdir(parents=True, exist_ok=True)
    dist.to_parquet(processed / OUT_NAME, index=False)
    results["district_file"] = str(processed / OUT_NAME)
    return results


def main(argv: list[str] | None = None) -> None:
    import json

    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.parse_args(argv)
    runlog.setup_logging()
    cfg = config.load("ml/susceptibility")
    with tracking.start_run("susceptibility", {"grid_deg": cfg["grid_deg"], **cfg["cv"],
                                               **cfg["model"], "features": cfg["features"]},
                            run_name="lgbm_block_cv") as run:
        res = tracked(run, cfg)
    print(json.dumps(res, indent=2, default=str))


def tracked(run: tracking.Run, cfg: dict) -> dict:
    """Fit, log every number to the run, apply the gate and save the results file."""
    import json

    res = fit_and_score(cfg)
    flat = {f"{k}.{m}": v for k, d in res.items() if isinstance(d, dict) and k != "importance_gain"
            for m, v in d.items() if isinstance(v, (int, float))}
    run.log_metrics(flat)
    gate = res["gate"]
    passed = tracking.record_gate(run, "flood_event_count_before_cutoff",
                                  gate["auc_count_before"], gate["auc_lgbm_terrain"],
                                  metric="auc_block_cv_later_events",
                                  margin=cfg["gate"].get("margin", 0.0))
    res["passed_gate"] = passed
    out = config.path("interim") / "susceptibility_results.json"
    out.write_text(json.dumps(res, indent=2, default=str))
    return res


if __name__ == "__main__":
    main()
