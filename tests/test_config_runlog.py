import csv

import pytest

from cri import config, runlog


def test_configs_load():
    assert config.load("project")["dates"]["quarter_end"] is True
    assert config.load("hazard")["cyclone"]["radius_km"] > 0
    assert config.path("raw_layers.gfd").name == "gfd"


def test_run_table_records_success_and_failure(tmp_path):
    table = tmp_path / "runs.csv"
    with runlog.run("unit", ["project", "hazard"], table=table) as outputs:
        outputs.append("data/processed/x.parquet")
    with pytest.raises(ValueError):
        with runlog.run("unit", ["project"], table=table):
            raise ValueError("boom")
    rows = list(csv.DictReader(table.open()))
    assert [r["status"] for r in rows] == ["ok", "failed"]
    assert rows[0]["outputs"] == "data/processed/x.parquet"
    assert len(rows[0]["config_hash"]) == 12


def test_config_hash_changes_with_content():
    assert runlog.config_hash(["project"]) != runlog.config_hash(["hazard"])


@pytest.mark.parametrize("as_list", [True, False])
def test_pipeline_runs_registered_steps(tmp_path, monkeypatch, as_list):
    from cri import pipeline

    out = tmp_path / "out.txt"

    def step():
        out.write_text("x")
        return [out] if as_list else out  # cri.hazard.validation.run returns one path

    monkeypatch.setitem(pipeline.STAGES, "hazard", ["tests.test_config_runlog:_noop"])
    monkeypatch.setattr(pipeline, "resolve", lambda s: step)
    monkeypatch.setattr(config, "path", lambda key: tmp_path / "runs.csv")
    pipeline.run_stage("hazard")
    assert out.exists()
    assert "out.txt" in (tmp_path / "runs.csv").read_text()
