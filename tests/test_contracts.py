import pandas as pd
import pytest

from cri.contracts import (
    REPO_ROOT,
    get_table,
    load_contracts,
    read_table,
    validate_frame,
    validate_samples,
)


def test_all_five_contracts_present():
    assert sorted(load_contracts()) == ["C1", "C2", "C3", "C4", "C5"]


def test_every_sample_passes():
    bad = {k: v for k, v in validate_samples().items() if v}
    assert not bad, bad


def _sample(contract, table):
    spec = get_table(contract, table)
    return read_table(REPO_ROOT / spec.sample, spec), spec


def test_crosswalk_weights_must_sum_to_one():
    df, spec = _sample("C1", "crosswalk_rbi_to_c2011")
    df.loc[df.rbi_name == "TOYNEWDIST", "weight"] = 0.3
    assert any("sum to 1" in e for e in validate_frame(df, spec))


def test_quarter_end_enforced():
    df, spec = _sample("C2", "panel_credit_deposit")
    df.loc[0, "quarter_end"] = pd.Timestamp("2018-06-15")
    assert any("quarter ends" in e for e in validate_frame(df, spec))


def test_duplicate_key_rejected():
    df, spec = _sample("C3", "hazard_scores")
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    assert any("primary key" in e for e in validate_frame(df, spec))


def test_treated_and_excluded_conflict():
    df, spec = _sample("C4", "event_district")
    df.loc[0, "excluded"] = True
    assert any("both treated and excluded" in e for e in validate_frame(df, spec))


def test_heavily_treated_implies_treated():
    df, spec = _sample("C4", "event_district")
    df.loc[2, "heavily_treated"] = True
    assert any("heavily_treated but not treated" in e for e in validate_frame(df, spec))


@pytest.mark.parametrize("col", ["ci_low", "ci_high"])
def test_effect_needs_interval(col):
    df, spec = _sample("C5", "effects")
    df.loc[0, col] = None
    assert validate_frame(df, spec)


def test_stress_interval_order():
    df, spec = _sample("C5", "stress_results")
    df.loc[0, "lower"] = 5000.0
    assert any("order" in e for e in validate_frame(df, spec))


def test_allowed_values_and_missing_columns():
    df, spec = _sample("C3", "flood_extent_district_event")
    df.loc[0, "source"] = "made_up"
    errs = validate_frame(df.drop(columns=["clear_view_share"]), spec)
    assert any("not allowed" in e for e in errs)
    assert any("missing columns" in e for e in errs)
