"""Phase 2 D lending exposure, on a synthetic panel (the real run waits for prereg-v1)."""

import pandas as pd
import pytest

from cri.exposure.district_exposure import (
    by_state,
    by_tier,
    concentration,
    reader_table,
    trend,
)

Q = pd.Timestamp
QS = [Q("2016-03-31"), Q("2016-06-30"), Q("2017-06-30"), Q("2017-09-30")]


def _panel(amounts):
    """amounts: {district_id: [amount per quarter in QS]}; credit, all banks, all sectors."""
    rows = []
    for d, vals in amounts.items():
        for q, a in zip(QS, vals, strict=True):
            rows.append({"district_id": d, "quarter_end": q, "bank_group": "all",
                         "measure": "credit", "sector": "all", "amount_cr": a,
                         "series_break": q == Q("2017-06-30")})
    return pd.DataFrame(rows)


def _scores():
    return pd.DataFrame({"district_id": [1, 2, 3, 4], "score_version": "weighted",
                         "hazard_type": "flood", "score": [0.9, 0.7, 0.3, 0.1],
                         "tier": [4, 3, 1, 1]})


MASTER = pd.DataFrame({"district_id": [1, 2, 3, 4], "state": ["A", "A", "B", "B"]})
PANEL = _panel({1: [10, 10, 20, 20], 2: [30, 30, 30, 30], 3: [40, 40, 30, 30],
                4: [20, None, 20, 20]})


def test_by_tier_shares_and_coverage():
    t = by_tier(PANEL, _scores(), 4).set_index(["quarter_end", "tier"])
    assert t.share[(QS[0], 4)] == pytest.approx(0.1)
    assert t.share[(QS[0], 1)] == pytest.approx(0.6)
    # district 4 has no figure in June 2016: shares over the other three
    assert t.share[(QS[1], 1)] == pytest.approx(0.5)
    assert t.coverage[(QS[1], 1)] == pytest.approx(0.75)
    assert t.groupby(level=0).share.sum().round(9).eq(1).all()
    assert t.series_break[(QS[2], 1)]


def test_concentration():
    c = concentration(PANEL, _scores(), [1, 2]).set_index("quarter_end")
    assert c.top1_share[QS[0]] == pytest.approx(0.1)
    assert c.top2_share[QS[0]] == pytest.approx(0.4)
    assert c.hhi[QS[0]] == pytest.approx(0.01 + 0.09 + 0.16 + 0.04)


def test_by_state():
    s = by_state(PANEL, _scores(), MASTER, [3, 4]).set_index(["quarter_end", "state"])
    assert s.high_share[(QS[0], "A")] == pytest.approx(1.0)
    assert s.high_share[(QS[0], "B")] == pytest.approx(0.0)
    assert s.amount_cr[(QS[0], "B")] == pytest.approx(60)


def test_trend_separates_breaks_from_regimes():
    tier = by_tier(PANEL, _scores(), 4)
    tr = trend(tier, [Q("2017-06-30")], [3, 4])
    regimes = tr[tr.kind == "regime"]
    jump = tr[tr.kind == "break"].iloc[0]
    # high share: 0.4, 0.5 (district 4 missing), then 0.5, 0.5
    assert jump.pp == pytest.approx(0.0)
    assert len(regimes) == 2
    assert regimes.iloc[1].pp == pytest.approx(0.0)


def test_reader_table():
    tier = by_tier(PANEL, _scores(), 4)
    r = reader_table(tier, "weighted", [3, 4]).iloc[0]
    assert r.quarter_end == QS[-1]
    assert r.very_high == pytest.approx(0.2)
    assert r.high == pytest.approx(0.3)
