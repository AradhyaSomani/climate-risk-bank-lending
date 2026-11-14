"""Annual BSR district credit by occupation (cri.ingest.rbi_annual), on small synthetic
sheets in each of the table's layouts."""

import io

import numpy as np
import pandas as pd
import pytest

from cri.ingest.rbi_annual import (
    merge_labels,
    number,
    occupation,
    parse_long,
    parse_wide,
    read_table,
    reconcile,
    repeated_columns,
    yearly_jumps,
)

Q = pd.Timestamp("2009-03-31")
OCC = ["I. AGRICULTURE", "1. Direct Finance", "II. INDUSTRY", "III. TRANSPORT OPERATORS",
       "IV. PROFESSIONAL AND OTHER SERVICES", "V. PERSONAL LOANS", "VI. TRADE",
       "VII. FINANCE", "VIII. ALL OTHERS", "TOTAL BANK CREDIT"]


def test_number_and_occupation():
    assert number("13,20,46") == 132046
    assert number("347,73,30I") == 3477330      # a stray letter in the 2010 table
    assert number("––") == 0 and np.isnan(number("")) and number(12.5) == 12.5
    assert occupation("I.        AGRICULTURE") == "agriculture"
    assert occupation("IV. PROFESSIONAL AND OTHER SERVICES") == "professional"
    assert occupation("VIII. ALL OTHERS") == "other"
    assert occupation("1. Direct Finance") is None
    assert occupation("TOTAL BANK CREDIT") == "total"


def _wide_sheet():
    """2009 style: names two rows above 'No. of', one name wrapped onto a second row."""
    rows = [["TABLE NO. 5.9 - ...", None, None, None, None, None],
            ["MARCH 2009", None, None, None, None, None],
            ["STATE : PUNJAB", None, "AMRITSAR", None, "SAHIBZADA AJIT SINGH", None],
            [None, None, None, None, "NAGAR", None],
            [None, None, None, None, None, None],
            [None, None, "No. of", "Amount", "No. of", "Amount"],
            ["OCCUPATION", None, "Accounts", "Out-", "Accounts", "Out-"]]
    for i, label in enumerate(OCC):
        roman, _, rest = label.partition(" ")
        a = 10 * (i + 1) if label != "TOTAL BANK CREDIT" else 450
        rows.append([roman, rest, 5, f"{a},00", 3, "––" if "FINANCE" in label else f"{a},00"])
    return pd.DataFrame(rows)


def test_parse_wide_reads_wrapped_names_and_nil():
    w = parse_wide({"PUNJAB": _wide_sheet()})
    assert set(w.rbi_district) == {"AMRITSAR", "SAHIBZADA AJIT SINGH NAGAR"}
    sas = w[w.rbi_district == "SAHIBZADA AJIT SINGH NAGAR"].set_index("occupation").amount
    assert sas["agriculture"] == 1000 and sas["finance"] == 0 and sas["total"] == 45000
    assert len(w) == 2 * 9                       # eight occupations and the total, sub-items out


def test_parse_wide_relabels_a_repeated_column():
    d = _wide_sheet()
    d.iat[2, 4], d.iat[3, 4] = "AMRITSAR", None
    w = parse_wide({"PUNJAB": d}, [{"state": "PUNJAB", "district": "AMRITSAR", "nth": 2,
                                    "rename": "TARN TARAN"}])
    assert set(w.rbi_district) == {"AMRITSAR", "TARN TARAN"}


def _long_sheet(header_lines: bool):
    """2011-2013 (a 'STATE: X DISTRICT: Y' line above each district) or 2014 on."""
    rows = [[None, "TABLE NO. 5.9 - ... MARCH 2014", None, None, None, None, None],
            [None, "REGION", "STATE", "DISTRICT", "OCCUPATION", "No. of Accounts", "Amount"]]
    for d in ["AMBALA", "BHIWANI"]:
        if header_lines:
            rows.append([None, None, None, f"NORTHERN REGION, STATE: HARYANA\n DISTRICT: {d}",
                         None, 100, 36000])
        for i, label in enumerate(OCC[:-1]):
            first = i == 0
            rows.append([None, "NORTHERN REGION" if first else None,
                         "HARYANA" if first and (d == "AMBALA" or header_lines) else None,
                         d if first else None, label, 10, 1000 * (i + 1)])
    return pd.DataFrame(rows)


@pytest.mark.parametrize("header_lines", [True, False])
def test_parse_long_both_layouts(header_lines):
    d = _long_sheet(header_lines)
    df = parse_long(d, 4)
    assert set(df.rbi_district) == {"AMBALA", "BHIWANI"}
    assert set(df.rbi_state) == {"HARYANA"}
    b = df[df.rbi_district == "BHIWANI"].set_index("occupation").amount
    assert b["industry"] == 3000
    assert ("total" in b.index) == header_lines


def test_read_table_converts_units_and_merges(tmp_path):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        _long_sheet(False).to_excel(xl, sheet_name="Table 5.9", header=False, index=False)
    cfg = {"unit_override": {2014: "thousand"},
           "merge": {"HARYANA": {"BHIWANI": "AMBALA"}}}
    df = read_table(buf.getvalue(), ".xlsx", cfg)
    assert df.quarter_end.iloc[0] == pd.Timestamp("2014-03-31")
    assert set(df.rbi_district) == {"AMBALA"}
    agri = df[df.occupation == "agriculture"].amount_cr.iloc[0]
    assert agri == pytest.approx(2 * 1000 * 1e-4)       # two districts, thousand -> crore


def _occ(amounts, total):
    rows = [{"quarter_end": Q, "rbi_state": "S", "rbi_district": "D", "occupation": o,
             "accounts": 1.0, "amount_cr": a} for o, a in amounts.items()]
    rows.append({"quarter_end": Q, "rbi_state": "S", "rbi_district": "D",
                 "occupation": "total", "accounts": 1.0, "amount_cr": total})
    return pd.DataFrame(rows)


PARTS = {"agriculture": 10.0, "industry": 20.0, "transport": 1.0, "professional": 2.0,
         "personal": 30.0, "trade": 5.0, "finance": 2.0, "other": 0.0}


def test_reconcile_fills_one_blank_and_nil():
    df, rev = reconcile(_occ({**PARTS, "finance": np.nan}, 70.0))
    fin = df.set_index("occupation").amount_cr
    assert fin["finance"] == pytest.approx(2.0) and len(rev) == 1
    df, rev = reconcile(_occ({**PARTS, "other": np.nan}, 70.0))
    assert df.set_index("occupation").amount_cr["other"] == 0 and rev.empty


def test_reconcile_picks_the_wrong_side_by_trend():
    years = [pd.Timestamp(f"{y}-03-31") for y in (2008, 2009, 2010)]
    frames = []
    for q, tot in zip(years, [70.0, 7.0, 70.0], strict=True):     # 2009 total has a typo
        frames.append(_occ(PARTS, tot).assign(quarter_end=q))
    df, rev = reconcile(pd.concat(frames, ignore_index=True))
    t = df[(df.occupation == "total")].set_index("quarter_end").amount_cr
    assert t[years[1]] == pytest.approx(70.0)
    assert "replaced by their sum" in rev.action.iloc[0]
    # a wrong occupation instead: the split goes missing, the total stays
    frames[1] = _occ({**PARTS, "industry": 2000.0}, 70.0).assign(quarter_end=years[1])
    df, rev = reconcile(pd.concat(frames, ignore_index=True))
    y = df[df.quarter_end == years[1]].set_index("occupation").amount_cr
    assert np.isnan(y["industry"]) and y["total"] == 70.0 and "missing" in rev.action.iloc[0]


def test_merge_labels_and_checks():
    df = pd.DataFrame({"rbi_state": "NCT OF DELHI", "rbi_district": ["EAST DELHI", "WEST DELHI",
                                                                      "OTHER"],
                       "occupation": "total", "accounts": 1.0, "amount": [1.0, 2.0, 5.0]})
    m = merge_labels(df, {"NCT OF DELHI": {"EAST DELHI": "DELHI", "WEST DELHI": "DELHI"}})
    assert m.set_index("rbi_district").amount.to_dict() == {"OTHER": 5.0, "DELHI": 3.0}

    a = _occ(PARTS, 70.0)
    b = a.assign(rbi_district="E")
    assert len(repeated_columns(pd.concat([a, b]))) == 2
    t = pd.concat([_occ(PARTS, 70.0), _occ(PARTS, 7000.0).assign(
        quarter_end=pd.Timestamp("2010-03-31"))])
    assert list(yearly_jumps(t, 1.6).index) == [pd.Timestamp("2010-03-31")]
