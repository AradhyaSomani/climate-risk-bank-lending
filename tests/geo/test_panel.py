"""Phase 1 C: the credit and deposit panel (contract C2)."""

import pandas as pd
import pytest
from toy_rbi import ALIASES, CFG, QUARTERS, _master, _rbi, _toy_rbi

from cri.exposure.panel import apply_crosswalk, build_panel, office_jumps
from cri.geo.crosswalk import build_crosswalk


def test_panel_sums_weights_and_keeps_missing_as_null():
    rbi = _toy_rbi()
    master = _master()
    xw = build_crosswalk(rbi, master, CFG, ALIASES)
    breaks = [{"quarter_end": "2005-09-30", "reason": "toy"}]
    panel = build_panel(rbi, xw, master, breaks)
    # full grid: 5 districts x 4 quarters x 2 measures
    assert len(panel) == 5 * 4 * 2
    assert not panel.duplicated(["district_id", "quarter_end", "measure"]).any()
    cred = panel[panel.measure == "credit"].set_index(["district_id", "quarter_end"])
    # parent and child add up to the undivided district in every quarter
    for q in QUARTERS:
        assert cred.amount_cr[(1, q)] + cred.amount_cr[(2, q)] == pytest.approx(40.0)
    assert cred.amount_cr[(2, QUARTERS[0])] == pytest.approx(10.0)  # 40 x 0.25
    assert cred.imputed_share[(2, QUARTERS[0])] == pytest.approx(1.0)
    assert cred.imputed_share[(1, QUARTERS[0])] == pytest.approx(1.0)
    assert cred.imputed_share[(1, QUARTERS[3])] == 0.0
    # the new district is added to its parent
    assert cred.amount_cr[(3, QUARTERS[3])] == pytest.approx(20.0)
    assert cred.amount_cr[(4, QUARTERS[0])] == pytest.approx(60.0)
    assert panel.series_break.sum() == 5 * 2
    assert (panel.data_version.str.match(r"^data-v\d+")).all()


def test_panel_amount_null_only_when_nothing_reported():
    rbi = _rbi([("OTHR", "TOY STATE", QUARTERS[0], None, None),
                ("OTHR", "TOY STATE", QUARTERS[1], 5.0, 5)])
    xw = pd.DataFrame({"rbi_name": ["OTHR"], "rbi_state": ["TOY STATE"],
                       "valid_from": [QUARTERS[0]], "valid_to": [pd.NaT],
                       "district_id": [3], "weight": [1.0], "match_type": ["fuzzy"]})
    agg = apply_crosswalk(rbi, xw)
    cred = agg[agg.measure == "credit"].set_index("quarter_end").amount_cr
    assert pd.isna(cred[QUARTERS[0]]) and cred[QUARTERS[1]] == 5.0


def test_rows_outside_every_interval_are_an_error():
    rbi = _toy_rbi()
    xw = build_crosswalk(rbi, _master(), CFG, ALIASES)
    xw = xw[xw.rbi_name != "CAPITAL"]
    with pytest.raises(ValueError, match="outside every crosswalk interval"):
        build_panel(rbi, xw, _master(), [])


def test_office_jumps_flags_a_doubling():
    panel = pd.DataFrame({
        "district_id": [1] * 4, "measure": ["deposits"] * 4,
        "quarter_end": QUARTERS, "n_offices": pd.array([20, 21, 44, 45], dtype="Int64"),
        "series_break": [False] * 4})
    j = office_jumps(panel)
    assert j.quarter_end.tolist() == [QUARTERS[2]]
