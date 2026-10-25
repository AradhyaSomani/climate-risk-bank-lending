"""Run tracking and the keep-or-drop gate for every model in src/cri/ml (Phase 2B-A).

Each run logs its parameters, metrics, the data version, the git commit, the hardware and
the run time to MLflow (a local store in `mlruns/`, see configs/paths.yaml). Without MLflow
installed the same record goes to `runs/ml/<component>.jsonl`, so tests and quick runs do
not need it.

The gate is the rule of the ML track: a model is kept only if it beats its stated baseline
on its stated metric. `record_gate` writes one row per run to `model_runs.parquet` (the
warehouse table `model_run`), and `keep_model` copies a model file to `data/models/` only
when its run passed.

    with tracking.start_run("susceptibility", params) as run:
        run.log_metrics({"auc_block_cv": 0.81})
        tracking.record_gate(run, "event_count", baseline_score=0.74, model_score=0.81)
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from cri import config
from cri.runlog import git_state

COMPONENTS = ["flood_cnn", "susceptibility", "graph", "statespace", "causal_ml", "extract"]


def hardware() -> dict:
    hw = {"platform": platform.platform(), "python": platform.python_version(),
          "cpu_count": os.cpu_count(), "device": "cpu"}
    try:
        import torch

        hw["torch"] = torch.__version__
        if torch.cuda.is_available():
            hw["device"] = torch.cuda.get_device_name(0)
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            hw["device"] = "mps"
    except ImportError:
        pass
    return hw


def _mlflow():
    if os.environ.get("CRI_NO_MLFLOW"):
        return None
    try:
        # newer MLflow refuses the plain file store unless told it is wanted; a local file
        # store keeps the project free of a tracking server
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        import mlflow

        return mlflow
    except ImportError:
        return None


@dataclass
class Run:
    component: str
    run_id: str
    params: dict
    metrics: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)
    backend: str = "jsonl"
    _mlflow: object = None

    def log_metrics(self, metrics: dict, step: int | None = None) -> None:
        clean = {k: float(v) for k, v in metrics.items()}
        self.metrics.update(clean)
        if self._mlflow is not None:
            self._mlflow.log_metrics(clean, step=step)

    def set_tags(self, tags: dict) -> None:
        self.tags.update({k: str(v) for k, v in tags.items()})
        if self._mlflow is not None:
            self._mlflow.set_tags(tags)

    def log_artifact(self, path: Path) -> None:
        if self._mlflow is not None:
            self._mlflow.log_artifact(str(path))


@contextmanager
def start_run(component: str, params: dict, run_name: str | None = None,
              tracking_dir: Path | None = None):
    if component not in COMPONENTS:
        raise ValueError(f"unknown component {component!r}; expected one of {COMPONENTS}")
    commit, dirty = git_state()
    tags = {"component": component, "git_commit": commit, "git_dirty": dirty,
            "data_version": config.load("project").get("data_version", "dev"),
            **{f"hw_{k}": v for k, v in hardware().items()}}
    started = time.time()
    mlflow = _mlflow()
    if mlflow is not None:
        store = tracking_dir or config.path("ml.mlruns")
        mlflow.set_tracking_uri(store.resolve().as_uri())
        mlflow.set_experiment(component)
        with mlflow.start_run(run_name=run_name) as r:
            run = Run(component, r.info.run_id, params, backend="mlflow", _mlflow=mlflow)
            mlflow.log_params({k: str(v)[:500] for k, v in params.items()})
            run.set_tags(tags)
            try:
                yield run
            finally:
                run.log_metrics({"run_seconds": time.time() - started})
        return
    run = Run(component, uuid.uuid4().hex, params)
    run.set_tags(tags)
    status = "failed"
    try:
        yield run
        status = "finished"
    finally:
        run.metrics["run_seconds"] = time.time() - started
        log_dir = tracking_dir or config.path("ml.jsonl")
        log_dir.mkdir(parents=True, exist_ok=True)
        rec = {"run_id": run.run_id, "run_name": run_name, "status": status,
               "params": params, "metrics": run.metrics, "tags": run.tags,
               "finished_at": datetime.now(timezone.utc).isoformat()}
        with (log_dir / f"{component}.jsonl").open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")


def record_gate(run: Run, baseline_name: str, baseline_score: float, model_score: float,
                metric: str = "", higher_is_better: bool = True, margin: float = 0.0,
                table: Path | None = None) -> bool:
    """Apply the gate (beat the baseline by more than `margin`) and store the result."""
    if higher_is_better:
        passed = model_score > baseline_score + margin
    else:
        passed = model_score < baseline_score - margin
    run.set_tags({"passed_gate": passed, "baseline_name": baseline_name, "gate_metric": metric})
    run.log_metrics({"gate_baseline_score": baseline_score, "gate_model_score": model_score})
    row = pd.DataFrame([{
        "run_id": run.run_id, "component": run.component, "metric": metric,
        "baseline_name": baseline_name, "baseline_score": float(baseline_score),
        "model_score": float(model_score), "passed_gate": bool(passed),
        "data_version": run.tags.get("data_version", "dev"),
        "code_version": run.tags.get("git_commit", "unknown"),
        "created_at": pd.Timestamp.now(tz="UTC"),
    }])
    table = table or config.path("ml.model_runs")
    table.parent.mkdir(parents=True, exist_ok=True)
    if table.exists():
        old = pd.read_parquet(table)
        row = pd.concat([old[old.run_id != run.run_id], row], ignore_index=True)
    row.to_parquet(table, index=False)
    return bool(passed)


def keep_model(run: Run, model_file: Path, passed: bool, models_dir: Path | None = None
               ) -> Path | None:
    """Copy a model that passed its gate to data/models/<component>/<run_id>/; else None."""
    if not passed:
        return None
    dest = (models_dir or config.path("ml.models")) / run.component / run.run_id
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / Path(model_file).name
    shutil.copy2(model_file, out)
    run.log_artifact(out)
    return out
