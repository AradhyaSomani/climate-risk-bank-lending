import numpy as np
import pandas as pd
import pytest

from cri.hazard import validation as val


def test_auc():
    s = pd.Series([0.1, 0.2, 0.8, 0.9])
    assert val.auc(s, pd.Series([False, False, True, True])) == 1.0
    assert val.auc(s, pd.Series([True, True, False, False])) == 0.0
    assert val.auc(pd.Series([1.0, 1.0]), pd.Series([True, False])) == 0.5
    assert np.isnan(val.auc(s, pd.Series([False] * 4)))


def test_emdat_states_counts_each_record_once_per_state():
    districts = pd.DataFrame({"district_id": [1, 2, 3, 4], "state": ["A", "A", "B", "C"]})
    scores = pd.DataFrame({
        "district_id": [1, 2, 3, 4] * 3,
        "score_version": np.repeat(["rank_avg", "weighted", "pca"], 4),
        "hazard_type": "flood", "score": [0.9, 0.7, 0.5, 0.1] * 3, "tier": 1,
    })
    records = pd.DataFrame({
        # record 1 names two districts of state A: counted once there
        "disno": ["1", "1", "2", "3", "4"],
        "district_id": [1, 2, pd.NA, 1, pd.NA],
        "state": [None, None, "B", None, "A"],
        "hazard_type": "flood",
        "total_damage_adj_kusd": [100.0, 100.0, 10.0, 50.0, 5.0],
    })
    out = val.emdat_states(scores, records, districts)
    row = out[(out.hazard == "flood") & (out.score_version == "rank_avg")].iloc[0]
    assert row.states == 3 and row.states_with_records == 2
    # state means 0.8 (A, 3 records, 155), 0.5 (B, 1, 10), 0.1 (C, 0, 0): perfectly ordered
    assert row.spearman_records == pytest.approx(1.0)
    assert row.spearman_damage == pytest.approx(1.0)


def test_gfd_vs_s1_compares_only_shared_events():
    flood = pd.DataFrame({
        "event_id": ["E1"] * 6 + ["E2"],
        "source": ["gfd"] * 3 + ["s1_otsu"] * 3 + ["s1_otsu"],
        "district_id": [1, 2, 3, 1, 2, 3, 1],
        "flooded_share": [0.0, 0.2, 0.5, 0.0, 0.3, 0.4, 0.2],
    })
    out = val.gfd_vs_s1(flood)
    assert out.event_id.tolist() == ["E1"]
    assert out.iloc[0].hit_iou == 1.0 and out.iloc[0].n_districts == 3


def test_summary_states_the_comparison():
    oos = pd.DataFrame({
        "hazard": "flood", "built_from": "before 2012", "tested_on": "2012 on",
        "score": ["rank_avg", "weighted", "pca", "flood_events_per_decade only"],
        "auc": [0.80, 0.81, 0.79, 0.85], "spearman_count": [0.5, 0.6, 0.5, 0.7],
    })
    text = val.summarise(oos)[0]
    assert "loses to" in text and "0.85" in text and "better (0.70 against 0.60)" in text


def test_summary_reports_emdat_when_present():
    em = pd.DataFrame({
        "hazard": ["flood"] * 3 + ["cyclone"] * 3, "score_version": ["a", "b", "c"] * 2,
        "spearman_records": [0.1, 0.2, 0.15, 0.6, 0.6, 0.6],
        "spearman_damage": [0.0, 0.1, 0.05, 0.4, 0.45, 0.5],
    })
    lines = val.summarise(pd.DataFrame(), em, {"flood": (25, 211)})
    text = "\n".join(lines)
    assert "cyclone records (Spearman 0.60 across" in text and "0.10 to 0.20" in text
    assert "25 of its 211 flood records" in text and "(sections 4 and 5)" in text
    assert "sections 3 to 5" in "\n".join(val.summarise(pd.DataFrame()))
