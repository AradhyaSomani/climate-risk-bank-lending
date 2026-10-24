"""Tests for the RBI district table reader, on small files shaped like DBIE exports."""

import pandas as pd
import pytest

from cri.ingest.rbi_bsr import (
    map_columns,
    parse_quarter_end,
    read_district_table,
    to_crore,
)


@pytest.mark.parametrize("unit,amount,expected", [
    ("crore", 5.0, 5.0),
    ("lakh", 250.0, 2.5),       # 100 lakh = 1 crore
    ("Lakh", 100.0, 1.0),
    ("million", 10.0, 1.0),     # 10 million = 1 crore
    ("thousand", 10_000.0, 1.0),
    ("billion", 1.0, 100.0),
])
def test_to_crore(unit, amount, expected):
    assert to_crore(amount, unit) == pytest.approx(expected)


def test_to_crore_rejects_unknown_unit():
    with pytest.raises(ValueError):
        to_crore(1.0, "rupees")


@pytest.mark.parametrize("label,expected", [
    ("2018-09-30", "2018-09-30"),
    ("28-Sep-2018", "2018-09-30"),       # last reporting Friday
    ("Sep-2018", "2018-09-30"),
    ("September 2018", "2018-09-30"),
    ("Mar-18", "2018-03-31"),
    ("2018-19:Q1", "2018-06-30"),        # fiscal Q1 = Apr to Jun
    ("2018-19:Q4", "2019-03-31"),
    ("Q3 2018-19", "2018-12-31"),
    ("Quarter ended December 2022", "2022-12-31"),
    (pd.Timestamp("2015-06-26"), "2015-06-30"),
])
def test_parse_quarter_end(label, expected):
    assert parse_quarter_end(label) == pd.Timestamp(expected)


def test_parse_quarter_end_returns_none_for_junk():
    assert parse_quarter_end("District-wise deposits") is None
    assert parse_quarter_end(None) is None


def test_map_columns_skips_ratio_columns():
    m = map_columns(["Region", "State Name", "District Name", "No. of Offices",
                     "Credit-Deposit Ratio", "Deposits", "Credit"])
    assert m["credit"] == "Credit"
    assert m["deposits"] == "Deposits"
    assert m["rbi_state"] == "State Name"
    assert m["n_offices"] == "No. of Offices"


def _write_xlsx(path, rows):
    pd.DataFrame(rows).to_excel(path, header=False, index=False)


def test_single_quarter_file_with_title_rows(tmp_path):
    f = tmp_path / "district_dep_credit_Sep-2018.xlsx"
    _write_xlsx(f, [
        ["District-wise Deposits and Credit of Scheduled Commercial Banks", None, None, None, None],
        ["(Amount in ₹ Lakh)", None, None, None, None],
        ["State", "District", "No. of Offices", "Deposits", "Credit"],
        ["KERALA", "ERNAKULAM", 900, "9,000,000", 6_000_000],
        [None, "ALAPPUZHA", 350, 3_000_000, 1_600_000],
        [None, "Total", 1250, 12_000_000, 7_600_000],
        ["ALL INDIA", None, None, None, None],
    ])
    out = read_district_table(f)
    assert set(out["quarter_end"]) == {pd.Timestamp("2018-09-30")}
    assert len(out) == 4  # 2 districts x 2 measures, total rows dropped
    ern = out[(out.rbi_district == "ERNAKULAM") & (out.measure == "deposits")].iloc[0]
    assert ern.unit == "lakh"
    assert ern.amount_cr == pytest.approx(90_000)
    assert (out["rbi_state"] == "KERALA").all()  # forward-filled
    assert ern.n_offices == 900


def test_period_column_and_explicit_unit(tmp_path):
    f = tmp_path / "panel.csv"
    pd.DataFrame([
        ["Quarter", "State", "District", "Deposits", "Credit"],
        ["Jun-2018", "Odisha", "Puri", 100.0, 40.0],
        ["Sep-2018", "Odisha", "Puri", 101.0, "-"],
    ]).to_csv(f, header=False, index=False)
    out = read_district_table(f, unit="crore")
    assert sorted(out["quarter_end"].unique()) == [pd.Timestamp("2018-06-30"), pd.Timestamp("2018-09-30")]
    missing = out[(out.measure == "credit") & (out.quarter_end == "2018-09-30")]
    assert missing["amount_cr"].isna().all()  # "-" means not reported, not zero


def test_missing_unit_is_an_error(tmp_path):
    f = tmp_path / "x_Mar-2019.csv"
    pd.DataFrame([["State", "District", "Deposits"], ["Kerala", "Idukki", 5]]).to_csv(f, header=False, index=False)
    with pytest.raises(ValueError, match="unit"):
        read_district_table(f)
