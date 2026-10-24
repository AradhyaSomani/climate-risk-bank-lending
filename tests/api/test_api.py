"""Contract tests for every endpoint of the read-only API, on the contract samples and on
parquet files built from them."""

import math

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cri import contracts  # noqa: E402
from cri.api import store as stores  # noqa: E402
from cri.api.app import create_app  # noqa: E402

ENDPOINTS = ["/hazard-scores", "/hazard-indicators", "/events", "/scenarios", "/effects",
             "/stress-results"]


def sample_table(resource):
    return stores.SampleStore().table(resource)


@pytest.fixture
def client():
    return TestClient(create_app(stores.SampleStore()))


@pytest.fixture
def parquet_dir(tmp_path):
    for name, r in stores.RESOURCES.items():
        if r.contract:
            sample_table(name).to_parquet(tmp_path / r.file, index=False)
    return tmp_path


def check_rows(rows, contract, table):
    """Rows back from the API satisfy the contract they came from."""
    spec = contracts.get_table(contract, table)
    df = pd.DataFrame(rows, columns=list(spec.columns))
    for col, cs in spec.columns.items():
        if cs["dtype"] == "date":
            df[col] = pd.to_datetime(df[col])
        elif cs["dtype"] == "float":
            df[col] = df[col].astype(float)
    assert contracts.validate_frame(df, spec) == []


@pytest.mark.parametrize("path", ENDPOINTS)
def test_envelope(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"resource", "data_version", "source", "n", "rows"} <= set(body)
    assert body["source"] == "sample"
    assert body["n"] == len(body["rows"]) > 0
    assert body["data_version"]


@pytest.mark.parametrize("path,contract,table", [
    ("/hazard-scores", "C3", "hazard_scores"),
    ("/hazard-indicators", "C3", "hazard_indicators"),
    ("/events", "C4", "events"),
    ("/scenarios", "C4", "scenarios"),
    ("/effects", "C5", "effects"),
])
def test_rows_meet_contract(client, path, contract, table):
    check_rows(client.get(path).json()["rows"], contract, table)


def test_nested_resources(client):
    ev = client.get("/events").json()["rows"][0]["event_id"]
    body = client.get(f"/events/{ev}/districts").json()
    assert body["n"] > 0 and all(r["event_id"] == ev for r in body["rows"])
    check_rows(body["rows"], "C4", "event_district")
    treated = client.get(f"/events/{ev}/districts", params={"treated": True}).json()["rows"]
    assert all(r["treated"] for r in treated)
    sc = client.get("/scenarios").json()["rows"][0]
    body = client.get(f"/scenarios/{sc['scenario_id']}/districts").json()
    assert body["hypothetical"] == sc["hypothetical"]
    assert client.get("/events/NOPE/districts").status_code == 404


def test_filters(client):
    rows = client.get("/hazard-scores", params={"hazard_type": "flood"}).json()["rows"]
    assert rows and {r["hazard_type"] for r in rows} == {"flood"}
    some = sample_table("hazard_scores").district_id.iloc[0]
    rows = client.get("/hazard-scores", params={"district_id": [int(some)]}).json()["rows"]
    assert rows and {r["district_id"] for r in rows} == {some}


def test_effects_carry_estimator_and_interval(client):
    body = client.get("/effects").json()
    assert body["estimators"] and body["interval"] == {"lower": "ci_low", "upper": "ci_high"}
    for r in body["rows"]:
        assert r["estimator"] and r["ci_low"] <= r["estimate"] <= r["ci_high"]


def test_no_stress_number_without_interval(parquet_dir):
    # one row with its interval removed: it must not come back
    sr = sample_table("stress_results")
    sr.loc[sr.index[0], "upper"] = float("nan")
    sr.to_parquet(parquet_dir / "stress_results.parquet", index=False)
    client = TestClient(create_app(stores.ParquetStore(parquet_dir)))
    body = client.get("/stress-results").json()
    assert body["withheld_without_interval"] == 1
    assert body["n"] == len(sr) - 1
    for r in body["rows"]:
        for k in ("median", "lower", "upper"):
            assert r[k] is not None and math.isfinite(r[k])
        assert r["lower"] <= r["median"] <= r["upper"]


@pytest.mark.parametrize("path", ENDPOINTS + ["/districts"])
def test_no_endpoint_serves_stress_without_interval(client, path):
    """Stress numbers (median) appear only next to a lower and an upper bound."""
    for r in client.get(path).json()["rows"]:
        if "median" in r:
            assert r.get("lower") is not None and r.get("upper") is not None


def test_parquet_store_and_missing_tables(parquet_dir):
    client = TestClient(create_app(stores.ParquetStore(parquet_dir)))
    body = client.get("/hazard-scores").json()
    assert body["source"] == "parquet" and body["n"] == len(sample_table("hazard_scores"))
    assert client.get("/exposure").status_code == 404  # B's table not built here
    health = client.get("/health").json()
    assert health["tables"]["hazard_scores"] > 0 and health["tables"]["exposure"] is None


def test_fallback_store(tmp_path):
    client = TestClient(create_app(stores.FallbackStore(stores.ParquetStore(tmp_path),
                                                        stores.SampleStore())))
    assert client.get("/events").json()["source"] == "sample"


def test_districts_geojson(client):
    body = client.get("/districts", params={"geometry": True}).json()
    assert body["n"] > 0
    feats = body["geojson"]["features"]
    assert len(feats) == body["n"]
    assert feats[0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}


def test_read_only(client):
    assert client.post("/hazard-scores").status_code == 405
    assert client.delete("/events").status_code == 405
