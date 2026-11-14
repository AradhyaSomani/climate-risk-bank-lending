"""Phase 0 E power check (cri.events.power), on small synthetic panels."""

import numpy as np
import pandas as pd
import pytest

from cri.events.power import (
    Window,
    blocked_spans,
    did_summary,
    estimate,
    free,
    log_outcome,
    match_weights,
    mde,
    placebo_rejections,
    power_curve,
    pseudo_windows,
    required,
    run,
)

Q = pd.Timestamp


def test_log_outcome_calendar_and_breaks():
    p = pd.DataFrame({
        "district_id": [1, 1, 1], "measure": "credit", "bank_group": "all", "sector": "all",
        "quarter_end": [Q("2016-06-30"), Q("2017-06-30"), Q("2017-09-30")],
        "amount_cr": [10.0, 20.0, 0.0], "series_break": [False, True, False]})
    y = log_outcome(p, "credit", break_missing=True)
    assert len(y) == 6                        # every calendar quarter, gaps as empty rows
    assert y.loc[Q("2016-09-30")].isna().all()
    assert np.isnan(y.loc[Q("2017-06-30"), 1])     # break quarter missing as drafted
    assert np.isnan(y.loc[Q("2017-09-30"), 1])     # non-positive amount
    assert log_outcome(p, "credit", break_missing=False).loc[Q("2017-06-30"), 1] == \
        pytest.approx(np.log(20))


def test_required_skips_quarters_nobody_has():
    rows = pd.DataFrame({1: [1.0, np.nan, 1.0], 2: [1.0, np.nan, np.nan]})
    assert not required(rows, False).any()
    assert required(rows, True).tolist() == [True, False]


def test_blocked_spans():
    ev = pd.DataFrame({"event_id": ["E"], "impact_quarter": [Q("2010-03-31")]})
    ed = pd.DataFrame({"event_id": ["E", "E"], "district_id": [1, 2],
                       "treated": [True, False], "excluded": [False, True]})
    spans = blocked_spans(ev, ed, after=12)
    assert spans[1] == [(Q("2010-03-31"), Q("2013-03-31"))] and 2 in spans
    assert free(spans, 1, Q("2007-01-01"), Q("2009-12-31"))
    assert not free(spans, 1, Q("2012-01-01"), Q("2014-12-31"))
    assert free(spans, 3, Q("2012-01-01"), Q("2014-12-31"))


def test_match_weights_sum_to_treated():
    rng = np.random.default_rng(0)
    xt, xc = rng.normal(size=(3, 2)), rng.normal(size=(20, 2))
    w = match_weights(xt, xc, 5, np.eye(2))
    assert w.sum() == pytest.approx(3) and (w >= 0).all()
    # an exact copy of a treated district is always among its nearest
    xc[7] = xt[0]
    assert match_weights(xt[:1], xc, 5, np.eye(2))[7] > 0


def test_did_summary_recovers_a_planted_effect():
    rng = np.random.default_rng(1)
    y = rng.normal(size=(12, 30)).cumsum(axis=0) * 0.01 + 5
    static = rng.normal(size=(30, 3))
    t, c = np.arange(5), np.arange(5, 30)
    x = np.column_stack([y[:8].mean(0), (y[7] - y[0]) / 7, static])
    vi = np.linalg.pinv(np.cov(x, rowvar=False))
    base = estimate(y, static, t, c, 5, vi)
    y2 = y.copy()
    y2[8:12, :5] += np.log(0.95)              # a 5% fall from quarter 0 on
    assert estimate(y2, static, t, c, 5, vi) - base == pytest.approx(np.log(0.95))
    # an unpublished quarter in 0..3 is left out of the mean
    y3 = y2.copy()
    y3[11] = np.nan
    w = match_weights(x[t], x[c], 5, vi)
    assert np.isfinite(did_summary(y3[:, t], y3[:, c], w))


def test_power_and_mde_on_known_noise():
    rng = np.random.default_rng(2)
    wins = [Window(Q("2010-03-31"), 0.0, rng.normal(0, 0.01, 4000)) for _ in range(3)]
    effects = np.array([0.0, 0.01, 0.05])
    pc = power_curve(wins, effects, 0.05)
    assert pc[0] == pytest.approx(0.05, abs=0.01)
    assert pc[2] > 0.99
    # normal theory: (1.96 + 0.84) * 0.01
    assert mde(wins, np.arange(0.001, 0.1, 0.001), 0.05, 0.8) == pytest.approx(0.028, abs=0.002)
    assert placebo_rejections(wins, 0.05) == 0.0
    assert np.isnan(mde([], np.arange(0.01, 0.1, 0.01), 0.05, 0.8))


def _toy(n=40, quarters=40, seed=3):
    rng = np.random.default_rng(seed)
    qs = pd.date_range("2004-03-31", periods=quarters, freq="QE")
    rows = []
    for d in range(1, n + 1):
        lvl = 5 + rng.normal(0, 1)
        for i, q in enumerate(qs):
            for m in ["credit", "deposits"]:
                rows.append({"district_id": d, "quarter_end": q, "measure": m,
                             "bank_group": "all", "sector": "all", "series_break": False,
                             "amount_cr": float(np.exp(lvl + 0.02 * i + rng.normal(0, 0.03)))})
    panel = pd.DataFrame(rows)
    master = pd.DataFrame({"district_id": range(1, n + 1),
                           "state": ["S"] * 10 + ["T"] * (n - 10),
                           "population": rng.integers(10**5, 10**6, n),
                           "urban_share": rng.uniform(0, 1, n)})
    controls = pd.DataFrame({"district_id": range(1, n + 1),
                             "ag_worker_share_2011": rng.uniform(0, 1, n)})
    events = pd.DataFrame({"event_id": ["FL-X"], "hazard_type": ["flood"], "states": ["S"],
                           "impact_quarter": [qs[30]]})
    ed = pd.DataFrame({"event_id": "FL-X", "district_id": [1, 2, 3, 4],
                       "treated": [True, True, True, False],
                       "heavily_treated": [True, False, False, False],
                       "excluded": [False, False, False, True]})
    return panel, events, ed, master, controls


CFG = {"measures": ["credit"], "effects": [0.05], "alpha": 0.05, "power": 0.8,
       "mde_pass": 0.10, "min_passing_events": 1, "k_controls": 3, "draws": 39,
       "pooled_draws": 200, "blocked_quarters": 12, "min_treated": 3, "min_controls": 10,
       "grid_max": 0.3, "seed": 1,
       "rules": {"proposed": {"series_break_missing": False, "skip_unpublished": True,
                              "text": "x"}},
       "power_rule": "proposed"}


def test_pseudo_windows_end_before_the_event():
    panel, events, ed, master, _ = _toy()
    y = log_outcome(panel, "credit", False)
    static = master.set_index("district_id")[["urban_share"]]
    spans = blocked_spans(events, ed, 12)
    wins = pseudo_windows(events.iloc[0], [1, 2, 3], [1, 2, 3, 5, 6, 7, 8, 9, 10],
                          list(range(5, 41)), y, static, spans, CFG, True,
                          np.random.default_rng(0))
    assert wins
    t0 = events.impact_quarter.iloc[0]
    assert all((w.tau.to_period("Q") + 3).end_time < t0 for w in wins)
    assert all(len(w.null) == CFG["draws"] and len(w.null_all) == CFG["draws"] for w in wins)


def test_run_on_toy_panel():
    table, res = run(*_toy(), CFG, ["FL-X"])
    row = table.iloc[0]
    assert row.treated == 3 and row.excluded == 1 and row.same_state_unaffected == 6
    assert row.treated_complete_credit_proposed == 3
    ev = res[res.event_id == "FL-X"].iloc[0]
    assert ev.pseudo_windows > 0 and 0 < ev.mde < 0.3
    assert ev.mde_worst >= ev.mde
    assert "pooled floods (proposed rule)" in set(res.event_id)
