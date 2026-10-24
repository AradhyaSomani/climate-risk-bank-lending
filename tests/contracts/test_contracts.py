"""Toy samples pass their contracts, and broken copies of them fail."""

import pandas as pd
import pytest

from cri.contracts.validate import REPO_ROOT, load_contract, read_table, validate_file, validate_frame

ALL_TABLES = [
    ("C1", "district_master"),
    ("C1", "crosswalk_rbi_to_c2011"),
    ("C2", "panel_credit_deposit"),
    ("C5", "effects"),
    ("C5", "stress_results"),
]


def _sample(code, table):
    spec = load_contract(code)["tables"][table]
    return read_table(REPO_ROOT / spec["sample"]), spec


@pytest.mark.parametrize("code,table", ALL_TABLES)
def test_toy_sample_passes(code, table):
    assert validate_file(code, table) == []


def test_full_district_master_needs_640_rows():
    df, spec = _sample("C1", "district_master")
    assert any("640" in p for p in validate_frame(df, spec, full=True))


def test_crosswalk_weights_must_sum_to_one():
    df, spec = _sample("C1", "crosswalk_rbi_to_c2011")
    df.loc[df["rbi_name"] == "TOY NEW DISTRICT", "weight"] = 0.5
    df.loc[df.index[-1], "weight"] = 0.4
    assert any("sum to 1" in p for p in validate_frame(df, spec, full=False))


def test_panel_rejects_non_quarter_end_dates():
    df, spec = _sample("C2", "panel_credit_deposit")
    df.loc[0, "quarter_end"] = "2018-04-01"
    assert any("quarter-end" in p for p in validate_frame(df, spec, full=False))


def test_panel_rejects_duplicate_keys():
    df, spec = _sample("C2", "panel_credit_deposit")
    df = pd.concat([df, df.iloc[[0]]])
    assert any("primary key" in p for p in validate_frame(df, spec, full=False))


def test_panel_rejects_negative_amounts_and_unknown_groups():
    df, spec = _sample("C2", "panel_credit_deposit")
    df.loc[0, "amount_cr"] = -5
    df.loc[1, "bank_group"] = "cooperative"
    problems = validate_frame(df, spec, full=False)
    assert any("below 0" in p for p in problems)
    assert any("not allowed" in p for p in problems)


def test_effects_interval_must_contain_estimate():
    df, spec = _sample("C5", "effects")
    df.loc[0, "estimate"] = df.loc[0, "ci_high"] + 1
    assert any("outside" in p for p in validate_frame(df, spec, full=False))


def test_missing_column_is_reported():
    df, spec = _sample("C5", "stress_results")
    problems = validate_frame(df.drop(columns=["lower"]), spec, full=False)
    assert any("missing columns" in p for p in problems)
