import json

import pandas as pd
import pytest

from cri.ml import tracking


@pytest.fixture(params=["jsonl", "mlflow"])
def backend(request, monkeypatch):
    if request.param == "jsonl":
        monkeypatch.setenv("CRI_NO_MLFLOW", "1")
    else:
        pytest.importorskip("mlflow")
        monkeypatch.delenv("CRI_NO_MLFLOW", raising=False)
    return request.param


def test_run_gate_and_keep(tmp_path, backend):
    table = tmp_path / "model_runs.parquet"
    with tracking.start_run("susceptibility", {"lr": 0.05}, tracking_dir=tmp_path / "t") as run:
        run.log_metrics({"auc": 0.8})
        passed = tracking.record_gate(run, "event_count", 0.7, 0.8, metric="auc", table=table)
        model = tmp_path / "m.txt"
        model.write_text("model")
        kept = tracking.keep_model(run, model, passed, models_dir=tmp_path / "models")
    assert run.backend == backend and passed and kept.exists()
    assert run.tags["passed_gate"] == "True" and "hw_cpu_count" in run.tags
    rows = pd.read_parquet(table)
    assert rows.iloc[0].component == "susceptibility" and bool(rows.iloc[0].passed_gate)
    if backend == "jsonl":
        rec = json.loads((tmp_path / "t" / "susceptibility.jsonl").read_text().splitlines()[0])
        assert rec["metrics"]["auc"] == 0.8 and rec["status"] == "finished"


def test_gate_lower_is_better_and_rerun_replaces_row(tmp_path, monkeypatch):
    monkeypatch.setenv("CRI_NO_MLFLOW", "1")
    table = tmp_path / "runs.parquet"
    with tracking.start_run("graph", {}, tracking_dir=tmp_path) as run:
        assert not tracking.record_gate(run, "h1", 1.0, 1.1, higher_is_better=False,
                                        table=table)
        assert tracking.record_gate(run, "h1", 1.0, 0.9, higher_is_better=False, table=table)
        assert tracking.keep_model(run, tmp_path / "x", False) is None
    rows = pd.read_parquet(table)
    assert len(rows) == 1 and bool(rows.iloc[0].passed_gate)


def test_unknown_component():
    with pytest.raises(ValueError), tracking.start_run("lstm", {}):
        pass
