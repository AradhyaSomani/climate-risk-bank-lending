"""Train and evaluate the U-Net against the baselines, by held-out event (Phase 2B-B).

Training uses patches from the training events; the epoch with the best mean water IoU on
the validation events is kept; the test events are scored once, on whole chips, on exactly
the pixels the baselines are scored on. The gate compares the model's mean test IoU with
the best baseline (Otsu on VV or VH per chip, or a fixed VV or VH threshold fitted on the
training events). Every run is logged with `cri.ml.tracking`, and its per-event scores are
appended to data/interim/flood_cnn/results.csv for the report.

    python -m cri.ml.flood_cnn.train --name sar_base16 --base 16 --epochs 15
    python -m cri.ml.flood_cnn.train --name sar_dem --channels vv vh dem slope
    python -m cri.ml.flood_cnn.train --name sar_noaug --no-augment
"""

from __future__ import annotations

import argparse
import copy
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from cri import config
from cri.ingest.sen1floods11 import chip_event
from cri.ml import tracking
from cri.ml.flood_cnn import baselines as bl
from cri.ml.flood_cnn.data import Split, chips, load_chip, load_splits, split_chips
from cri.ml.flood_cnn.model import UNet, augment, dice_ce_loss

log = logging.getLogger(__name__)


def out_dir() -> Path:
    return config.path("interim") / "flood_cnn"


def class_weights(y: np.ndarray) -> torch.Tensor:
    n = np.array([(y == 0).sum(), (y == 1).sum()], dtype=float)
    w = n.sum() / np.maximum(n, 1) / 2
    return torch.tensor(w / w.mean(), dtype=torch.float32)


@torch.no_grad()
def predict(model: UNet, x: np.ndarray, batch: int = 8) -> np.ndarray:
    model.eval()
    out = []
    for i in range(0, len(x), batch):
        out.append(model(torch.from_numpy(x[i:i + batch])).argmax(1).numpy())
    return np.concatenate(out) if out else np.zeros((0,) + x.shape[2:], dtype=int)


def split_scores(model: UNet, split: Split) -> pd.DataFrame:
    pred = predict(model, split.x)
    rows = [{"event": e, **bl.confusion(p == 1, y)}
            for e, p, y in zip(split.meta.event, pred, split.y, strict=True)]
    return bl.by_event(pd.DataFrame(rows))


def chip_scores(model: UNet, chip_ids: list[str], channels: list[str]) -> pd.DataFrame:
    """Whole-chip scores (512 x 512), comparable with the baselines pixel for pixel."""
    rows = []
    for chip in chip_ids:
        x, y, _ = load_chip(chip, channels)
        p = predict(model, x[None])[0]
        rows.append({"chip": chip, "event": chip_event(chip), **bl.confusion(p == 1, y)})
    return bl.by_event(pd.DataFrame(rows))


def train(splits: dict[str, Split], cfg: dict, run: tracking.Run | None = None,
          max_batches: int | None = None) -> tuple[UNet, pd.DataFrame]:
    tr, m = cfg["train"], cfg["model"]
    torch.manual_seed(tr["seed"])
    gen = torch.Generator().manual_seed(tr["seed"])
    model = UNet(len(cfg["data"]["channels"]), 2, m["base_channels"], m["depth"])
    opt = torch.optim.AdamW(model.parameters(), lr=tr["lr"], weight_decay=tr["weight_decay"])
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=tr["epochs"])
    w = class_weights(splits["train"].y) if tr["class_weights"] == "auto" else None
    x_all = torch.from_numpy(splits["train"].x)
    y_all = torch.from_numpy(splits["train"].y.astype("int64"))
    best, best_iou, history = None, -1.0, []
    for epoch in range(tr["epochs"]):
        model.train()
        order = torch.randperm(len(y_all), generator=gen)
        losses, t0 = [], time.time()
        for b, i in enumerate(range(0, len(order), tr["batch_size"])):
            if max_batches is not None and b >= max_batches:
                break
            idx = order[i:i + tr["batch_size"]]
            x, y = x_all[idx], y_all[idx]
            if tr["augment"]:
                x, y = augment(x, y, gen)
            opt.zero_grad()
            loss = dice_ce_loss(model(x), y, w, tr["dice_weight"])
            loss.backward()
            opt.step()
            losses.append(float(loss.detach()))
        sched.step()
        val = split_scores(model, splits["val"])
        val_iou = float(val.loc[val.event == "mean", "iou_water"].iloc[0])
        history.append({"epoch": epoch, "loss": float(np.mean(losses)), "val_iou": val_iou,
                        "seconds": time.time() - t0})
        log.info("epoch %d loss %.4f val IoU %.3f (%.0f s)", epoch, history[-1]["loss"],
                 val_iou, history[-1]["seconds"])
        if run is not None:
            run.log_metrics({"train_loss": history[-1]["loss"], "val_iou": val_iou}, step=epoch)
        if val_iou > best_iou:
            best_iou, best = val_iou, copy.deepcopy(model.state_dict())
    model.load_state_dict(best)
    return model, pd.DataFrame(history)


def run_experiment(name: str, cfg: dict, max_batches: int | None = None) -> pd.DataFrame:
    data_cfg = cfg["data"]
    parts = split_chips(chips(), data_cfg["test_events"], data_cfg["val_events"])
    splits = load_splits(data_cfg)
    params = {"name": name, **{f"data.{k}": v for k, v in data_cfg.items()},
              **{f"model.{k}": v for k, v in cfg["model"].items()},
              **{f"train.{k}": v for k, v in cfg["train"].items()},
              "n_train_patches": len(splits["train"].y)}
    with tracking.start_run("flood_cnn", params, run_name=name) as run:
        model, history = train(splits, cfg, run, max_batches)
        test = chip_scores(model, parts["test"], data_cfg["channels"]).assign(method=name)
        fixed = {f"fixed_{b}": bl.fit_fixed_threshold(parts["train"], i)
                 for i, b in enumerate(["vv", "vh"])}
        base = bl.baseline_scores(parts["test"], fixed)
        means = base[base.event == "mean"].set_index("method").iou_water
        best_name = means.idxmax()
        model_iou = float(test.loc[test.event == "mean", "iou_water"].iloc[0])
        run.log_metrics({f"test_iou_{e}": v for e, v in zip(test.event, test.iou_water,
                                                             strict=True)})
        passed = tracking.record_gate(run, best_name, float(means.max()), model_iou,
                                      metric=cfg["gate"]["metric"],
                                      margin=cfg["gate"].get("margin", 0.0))
        d = out_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.pt"
        torch.save({"state_dict": model.state_dict(), "config": cfg}, path)
        tracking.keep_model(run, path, passed)
        history.to_csv(d / f"{name}_history.csv", index=False)
        res = pd.concat([test, base], ignore_index=True).assign(
            run=name, run_id=run.run_id, passed_gate=passed, best_epoch=int(
                history.val_iou.idxmax()), epochs=len(history),
            train_minutes=round(history.seconds.sum() / 60, 1))
        res_path = d / "results.csv"
        old = pd.read_csv(res_path) if res_path.exists() else pd.DataFrame()
        if len(old):
            old = old[old.run != name]
        pd.concat([old, res], ignore_index=True).to_csv(res_path, index=False)
    log.info("%s: test IoU %.3f vs %s %.3f -> %s", name, model_iou, best_name, means.max(),
             "passed" if passed else "failed")
    return res


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--channels", nargs="*")
    p.add_argument("--base", type=int)
    p.add_argument("--epochs", type=int)
    p.add_argument("--no-augment", action="store_true")
    p.add_argument("--max-batches", type=int, help="cap batches per epoch (smoke runs)")
    p.add_argument("--threads", type=int)
    a = p.parse_args(argv)
    runlog.setup_logging()
    if a.threads:
        torch.set_num_threads(a.threads)
    cfg = copy.deepcopy(config.load("ml/flood_cnn"))
    if a.channels:
        cfg["data"]["channels"] = a.channels
    if a.base:
        cfg["model"]["base_channels"] = a.base
    if a.epochs:
        cfg["train"]["epochs"] = a.epochs
    if a.no_augment:
        cfg["train"]["augment"] = False
    res = run_experiment(a.name, cfg, a.max_batches)
    print(res[res.event == "mean"][["method", "iou_water", "f1_water"]].to_string(index=False))


if __name__ == "__main__":
    main()
