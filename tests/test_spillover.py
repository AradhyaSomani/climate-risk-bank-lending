import numpy as np
import pandas as pd
import pytest

from cri.events import spillover as sp


def test_rings_on_a_line():
    adj = {1: {2}, 2: {1, 3}, 3: {2, 4}, 4: {3, 5}, 5: {4}}
    assert sp.rings({1}, adj) == {1: 0, 2: 1, 3: 2}
    assert sp.rings({3}, adj, depth=1) == {3: 0, 2: 1, 4: 1}


def test_ring_did_recovers_a_planted_spillover():
    rng = np.random.default_rng(0)
    q = pd.date_range("2010-03-31", periods=20, freq="QE")
    ids = np.arange(1, 61)
    lvl = pd.DataFrame(5 + 0.01 * np.arange(20)[:, None] + rng.normal(0, 0.002, (20, 60)),
                       index=q, columns=ids)
    ring_of = {d: 0 for d in ids[:10]} | {d: 1 for d in ids[10:25]}
    q0 = q[10]
    lvl.loc[q0:, ids[:10]] -= 0.05   # treated fall 5%
    lvl.loc[q0:, ids[10:25]] -= 0.02  # neighbours fall 2%
    ch = sp.window_change(lvl, q0)
    res = sp.ring_did(ch, ring_of, excluded=set(), n_boot=200).set_index("ring")
    assert res.loc[0, "estimate"] == pytest.approx(-0.05, abs=0.005)
    assert res.loc[1, "estimate"] == pytest.approx(-0.02, abs=0.005)
    assert res.loc[1, "lower"] < -0.02 < res.loc[1, "upper"]
    assert res.loc[1, "n_control"] == 35
