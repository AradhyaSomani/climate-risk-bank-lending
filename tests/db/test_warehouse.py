"""Warehouse tests against a real PostGIS. Set CRI_TEST_DATABASE_URL to a scratch database
(it is wiped); skipped otherwise, and in CI."""

import os

import geopandas as gpd
import pandas as pd
import pytest
from shapely import wkt

from cri.contracts import REPO_ROOT, get_table, read_table

URL = os.environ.get("CRI_TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="CRI_TEST_DATABASE_URL not set")]


@pytest.fixture
def processed(tmp_path):
    """Contract toy samples written as processed parquet files."""
    spec = get_table("C1", "district_master")
    dm = read_table(REPO_ROOT / spec.sample, spec)
    gdf = gpd.GeoDataFrame(dm.drop(columns="geometry"),
                           geometry=dm.geometry.map(wkt.loads), crs="EPSG:4326")
    gdf.to_parquet(tmp_path / "district_master.parquet")
    for contract, table, fname in [
        ("C1", "crosswalk_rbi_to_c2011", "crosswalk_rbi_to_c2011.parquet"),
        ("C2", "panel_credit_deposit", "panel_credit_deposit.parquet"),
        ("C3", "flood_extent_district_event", "flood_extent_district_event.parquet"),
        ("C3", "hazard_scores", "hazard_scores.parquet"),
        ("C4", "events", "events.parquet"),
        ("C4", "scenarios", "scenarios.parquet"),
        ("C5", "effects", "effects.parquet"),
        ("C5", "stress_results", "stress_results.parquet"),
    ]:
        sp = get_table(contract, table)
        read_table(REPO_ROOT / sp.sample, sp).to_parquet(tmp_path / fname)
    return tmp_path


@pytest.fixture
def conn_url(monkeypatch, processed):
    import psycopg

    from cri import config

    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    real = config.path
    monkeypatch.setattr(config, "path", lambda k: processed if k == "processed" else real(k))
    return URL


def test_load_is_idempotent_and_queries_work(conn_url, processed):
    import psycopg

    from cri.db.load import load_all

    first = load_all(conn_url, processed)
    second = load_all(conn_url, processed)
    assert first == second
    assert first["district"] == 5 and first["flood_extent"] == 3
    assert first["credit_deposit"] == 32 and first["effect"] == 3 and first["stress_result"] == 2

    with psycopg.connect(conn_url) as c:
        # districts within a polygon (the sample boxes: Ernakulam north of 9.8N)
        rows = c.execute(
            "SELECT district_id FROM district WHERE ST_Intersects(geom, "
            "ST_MakeEnvelope(76.3, 10.0, 76.5, 10.2, 4326)) ORDER BY 1"
        ).fetchall()
        assert [r[0] for r in rows] == [595]
        # district by event, joined to its hazard score
        rows = c.execute(
            "SELECT d.name, f.flooded_share, s.tier FROM flood_extent f "
            "JOIN district d USING (district_id) "
            "JOIN hazard_score s ON s.district_id = f.district_id AND s.hazard_type = 'flood' "
            "WHERE f.event_id = 'FL-2018-KER' ORDER BY f.flooded_share DESC"
        ).fetchall()
        assert rows[0][0] == "Alappuzha" and rows[0][2] == 4
        c.execute("SET enable_seqscan = off")
        plan = " ".join(r[0] for r in c.execute(
            "EXPLAIN SELECT 1 FROM district WHERE ST_Intersects(geom, "
            "ST_MakeEnvelope(76, 9, 77, 10, 4326))").fetchall())
        assert "district_geom_idx" in plan


def test_rows_removed_from_file_leave_the_table(conn_url, processed):
    from cri.db.load import load_all

    load_all(conn_url, processed)
    f = pd.read_parquet(processed / "flood_extent_district_event.parquet")
    f.iloc[:2].to_parquet(processed / "flood_extent_district_event.parquet")
    assert load_all(conn_url, processed)["flood_extent"] == 2


def test_b_columns_reach_the_warehouse(conn_url, processed):
    """B's C1, C2 and C5 columns are stored, including C5 `primary` and pooled effects."""
    import psycopg

    from cri.api.store import PostgresStore
    from cri.db.load import load_all

    load_all(conn_url, processed)
    with psycopg.connect(conn_url) as c:
        assert c.execute("SELECT count(*) FROM district WHERE state_code = 32").fetchone()[0] == 5
        assert c.execute("SELECT count(*) FROM district_crosswalk WHERE match_type = 'split'"
                         ).fetchone()[0] == 2
        assert c.execute("SELECT count(*) FROM credit_deposit WHERE imputed_share IS NULL"
                         ).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM effect WHERE event_id = 'pooled'"
                         ).fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM stress_result WHERE hypothetical"
                         ).fetchone()[0] == 1
    effects = PostgresStore(conn_url).table("effects")
    assert "primary" in effects and "is_primary" not in effects
    assert int(effects["primary"].sum()) == 1
