"""Data tests on the real processed tables (Phase 1J). Each test is skipped when its file
has not been built, so the suite runs anywhere; on a full checkout with data they all run."""

import numpy as np
import pandas as pd
import pytest

from cri import config, contracts

PROCESSED = config.path("processed")


def _need(name):
    path = PROCESSED / name
    if not path.exists():
        pytest.skip(f"{name} not built")
    return pd.read_parquet(path)


def _contract_tables():
    for cid, tables in contracts.load_contracts().items():
        for tname, spec in tables.items():
            yield pytest.param(cid, tname, spec, id=f"{cid}.{tname}")


@pytest.mark.parametrize("cid,tname,spec", list(_contract_tables()))
def test_processed_file_meets_contract(cid, tname, spec):
    path = contracts.REPO_ROOT / spec.file
    if not path.exists():
        pytest.skip(f"{spec.file} not built")
    assert contracts.validate_file(cid, tname, path) == []


def test_flood_extent_consistency():
    f = _need("flood_extent_district_event.parquet")
    assert (f.flooded_share <= f.mapped_share + 1e-6).all()
    assert (f.flooded_km2 >= 0).all()
    assert f.event_id.str.match(r"^(GFD|S1|FL)-").all()
    # each GFD event covers at least one district
    assert f.groupby("event_id").size().min() >= 1


def test_cyclone_exposure_consistency():
    c = _need("cyclone_exposure_district_event.parquet")
    hz = config.load("hazard")["cyclone"]
    assert (c.track_dist_km <= hz["max_report_km"] + 1e-6).all()
    assert not (c.within_radius & (c.track_dist_km > hz["radius_km"])).any()
    # landfall is a storm-level value: one per event
    assert (c.groupby("event_id").landfall_time.nunique(dropna=False) <= 1).all()


def test_baseline_ranges():
    b = _need("hazard_baseline_district.parquet")
    assert b.district_id.is_unique and len(b) == 640
    for col in ["perm_water_share", "lowlying_share", "gfd_max_flooded_share"]:
        if col in b:
            v = b[col].dropna()
            assert ((v >= 0) & (v <= 1)).all(), col
    if "slope_mean_deg" in b:
        assert b.slope_mean_deg.dropna().between(0, 60).all()
    if "landfall_count" in b:
        assert (b.landfall_count >= b.landfall_count_strong).all()


def test_district_geometry_valid():
    from cri.geo.districts import load_districts

    path = config.district_geometry_path()
    if not path.exists():
        pytest.skip("no district geometry")
    d = load_districts()
    assert d.geometry.is_valid.all()
    assert d.district_id.is_unique
    assert np.isclose(d.area_km2.sum(), 3.19e6, rtol=0.05)  # India incl. claimed areas


def test_crosswalk_covers_every_rbi_figure():
    """Phase 1 B: every RBI district-quarter with a figure maps to a 2011 district."""
    from cri.exposure.panel import check_labels_used
    from cri.ingest.rbi_bsr import interim_path

    xw = _need("crosswalk_rbi_to_c2011.parquet")
    if not interim_path().exists():
        pytest.skip("RBI interim table not built")
    check_labels_used(pd.read_parquet(interim_path()), xw)


def test_panel_grid_and_keys():
    """Phase 1 C/J: one row per district, quarter and measure for all 640 districts."""
    p = _need("panel_credit_deposit.parquet")
    assert p.district_id.nunique() == 640
    n_q = p.quarter_end.nunique()
    assert len(p) == 640 * n_q * 2
    assert not p.duplicated(["district_id", "quarter_end", "bank_group", "measure",
                             "sector"]).any()
    assert (p.quarter_end == p.quarter_end + pd.offsets.QuarterEnd(0)).all()
    assert (p.amount_cr.dropna() >= 0).all()
    assert p.imputed_share.between(0, 1).all()


def test_panel_test_states_complete():
    """Kerala, Odisha and Tamil Nadu (the audit's test states) have every district in every
    quarter, for both measures."""
    p = _need("panel_credit_deposit.parquet")
    m = _need("district_master.parquet")
    ids = m.loc[m.state.isin(["Kerala", "Odisha", "Tamil Nadu"]), "district_id"]
    assert p[p.district_id.isin(ids)].amount_cr.notna().all()


def test_controls_grid():
    """Phase 1 D: one row per district and quarter; rates in range where filled."""
    c = _need("controls_district_quarter.parquet")
    assert c.district_id.nunique() == 640
    assert len(c) == 640 * c.quarter_end.nunique()
    assert not c.duplicated(["district_id", "quarter_end"]).any()
    for col in ["urban_share_2011", "ag_worker_share_2011", "literacy_2011"]:
        assert c[col].between(0, 1).all(), col
    assert (c.rain_mm.dropna() >= 0).all()
    assert (c.quarters_since_waiver.dropna() >= 0).all()
