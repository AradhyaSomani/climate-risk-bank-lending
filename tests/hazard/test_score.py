import numpy as np
import pandas as pd
import pytest

from cri import contracts
from cri.hazard import score as sc

CFG = {
    "direction": {"rel_elev": -1},
    "weights": {"flood": {"f_freq": 0.5, "f_share": 0.3, "rel_elev": 0.2},
                "cyclone": {"c_freq": 0.6, "c_wind": 0.4}},
    "tier_cutoffs": [0.5, 0.75, 0.9],
}


def indicators(n=20, seed=0):
    rng = np.random.default_rng(seed)
    base = np.arange(n, dtype=float)
    return pd.DataFrame({
        "district_id": np.arange(1, n + 1),
        "f_freq": base + rng.normal(0, 1, n),
        "f_share": base / n + rng.normal(0, 0.05, n),
        "rel_elev": 100 - base * 4,  # lower ground in the higher-hazard districts
        "c_freq": np.r_[np.zeros(n // 2), np.arange(n // 2, dtype=float)][::-1],
        "c_wind": np.r_[np.zeros(n // 2), np.linspace(40, 120, n // 2)][::-1],
    })


def test_pct_rank_puts_tied_zeros_at_the_bottom():
    p = sc.pct_rank(pd.Series([0, 0, 0, 5, 10]))
    assert p.tolist() == [0, 0, 0, 0.75, 1.0]


def test_tiers_from_cutoffs():
    t = sc.tiers(pd.Series(np.arange(101, dtype=float)), [0.5, 0.75, 0.9])
    assert t.iloc[0] == 1 and t.iloc[49] == 1 and t.iloc[50] == 2
    assert t.iloc[75] == 3 and t.iloc[90] == 4 and t.iloc[100] == 4
    assert t.value_counts().sort_index().tolist() == [50, 25, 15, 11]


def test_weighted_renormalises_missing():
    x = pd.DataFrame({"a": [0.0, 1.0, 2.0], "b": [0.0, np.nan, 2.0]})
    s = sc.score_weighted(x, {"a": 0.75, "b": 0.25})
    assert s.iloc[1] == pytest.approx(0.5)  # only "a" is known: its percentile
    assert s.iloc[2] == pytest.approx(1.0)


def test_pca_is_signed_like_rank_avg():
    x = pd.DataFrame({"a": [1.0, 2, 3, 4, 5], "b": [2.0, 4, 5, 9, 11]})
    pc, load, expl = sc.score_pca(-x)  # every indicator reversed: still oriented to rank_avg
    assert pc.corr(sc.score_rank_avg(-x), method="spearman") > 0.99
    assert expl > 0.9 and len(load) == 2


def test_compute_versions_combined_and_contract():
    scores, info = sc.compute(indicators(), CFG)
    assert set(scores.score_version) == {"rank_avg", "weighted", "pca"}
    assert set(scores.hazard_type) == {"flood", "cyclone", "combined"}
    assert len(scores) == 20 * 3 * 3
    w = scores.pivot_table(index=["score_version", "district_id"], columns="hazard_type",
                           values="tier")
    assert (w.combined == w[["flood", "cyclone"]].max(axis=1)).all()
    ra = scores[(scores.score_version == "rank_avg") & (scores.hazard_type == "flood")]
    # rel_elev is reversed, so the low-lying, often-flooded district 20 is on top
    assert ra.set_index("district_id").score.idxmax() == 20
    assert {"flood", "cyclone"} <= set(info)
    spec = contracts.get_table("C3", "hazard_scores")
    assert contracts.validate_frame(scores.assign(data_version="test"), spec) == []


def test_stability_counts_agreement():
    s = pd.DataFrame({
        "district_id": [1, 2, 1, 2, 1, 2], "hazard_type": "flood",
        "score_version": ["rank_avg", "rank_avg", "weighted", "weighted", "pca", "pca"],
        "tier": [1, 4, 1, 3, 1, 4],
    })
    st = sc.stability(s).iloc[0]
    assert st["rank_avg=weighted"] == 0.5 and st["rank_avg=pca"] == 1.0
    assert st.all_three == 0.5 and st.within_one_tier == 1.0
