"""Report 1 helpers (cri.exposure.report1), on a small synthetic panel."""

import pandas as pd
import pytest

from cri.exposure.district_exposure import by_tier
from cri.exposure.report1 import high_share, md_table, pct, snapshot, states, top_districts

Q = pd.Timestamp("2026-03-31")


def _panel():
    rows = []
    for d, credit, dep in [(1, 50, 40), (2, 20, 30), (3, 20, 20), (4, 10, 10)]:
        for m, a in [("credit", credit), ("deposits", dep)]:
            rows.append({"district_id": d, "quarter_end": Q, "bank_group": "all",
                         "sector": "all", "measure": m, "amount_cr": float(a),
                         "series_break": False})
    return pd.DataFrame(rows)


def _scores():
    rows = []
    for hz, tiers in [("flood", [4, 1, 3, 1]), ("cyclone", [3, 4, 1, 1]),
                      ("combined", [4, 4, 3, 1])]:
        for d, t in zip([1, 2, 3, 4], tiers, strict=True):
            rows.append({"district_id": d, "score_version": "weighted", "hazard_type": hz,
                         "score": float(t), "tier": t})
    return pd.DataFrame(rows)


MASTER = pd.DataFrame({"district_id": [1, 2, 3, 4], "name": ["M", "B", "C", "D"],
                       "state": ["X", "X", "Y", "Y"], "population": [10, 30, 40, 20]})


def test_pct():
    assert pct(0.564) == "56%"
    assert pct(0.0123, 1) == "1.2%"
    assert pct(float("nan")) == "n/a"


def test_high_share_sums_high_tiers():
    hs = high_share(by_tier(_panel(), _scores(), 4), [3, 4]).set_index(
        ["measure", "hazard_type"]).share
    assert hs[("credit", "flood")] == pytest.approx(0.7)
    assert hs[("credit", "combined")] == pytest.approx(0.9)
    assert hs[("deposits", "cyclone")] == pytest.approx(0.7)


def test_snapshot_with_and_without_metros():
    s = snapshot(_panel(), _scores(), MASTER, Q, "weighted", [3, 4], [1]) \
        .set_index("hazard_type")
    assert s.loc["flood", "districts"] == pytest.approx(0.5)
    assert s.loc["flood", "population"] == pytest.approx(0.5)
    assert s.loc["flood", "credit"] == pytest.approx(0.7)
    # without district 1: flood-high credit is district 3 only, 20 of 50
    assert s.loc["flood", "credit_ex_metro"] == pytest.approx(0.4)
    assert s.loc["combined", "deposits_ex_metro"] == pytest.approx(50 / 60)


def test_top_districts_very_high_combined():
    t = top_districts(_panel(), _scores(), MASTER, Q, "weighted", 5)
    assert t.name.tolist() == ["M", "B"]
    assert t.share.tolist() == pytest.approx([0.5, 0.2])


def test_states_share_of_india_high():
    bs = pd.DataFrame({"quarter_end": Q, "measure": "credit", "score_version": "weighted",
                       "hazard_type": "combined", "bank_group": "all", "sector": "all",
                       "state": ["X", "Y"], "amount_cr": [70.0, 30.0],
                       "high_share": [1.0, 2 / 3]})
    s = states(bs, Q, "weighted", 2)
    assert s.state.tolist() == ["X", "Y"]
    assert s.of_india_high.tolist() == pytest.approx([0.7 / 0.9, 0.2 / 0.9])


def test_md_table():
    lines = md_table(pd.DataFrame({"a": [1], "b": ["x"]}))
    assert lines[0] == "| a | b |" and lines[1] == "| --- | --- |" and lines[2] == "| 1 | x |"
