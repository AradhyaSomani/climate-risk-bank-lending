"""Annual credit by sector on Census 2011 districts (cri.exposure.sector_panel)."""

import numpy as np
import pandas as pd
import pytest

from cri.exposure.sector_panel import build_sector_panel, merged_config, to_sectors

Q = pd.Timestamp("2020-03-31")


def _occ():
    amounts = {"agriculture": 10.0, "industry": 20.0, "transport": 1.0, "professional": 2.0,
               "personal": 30.0, "trade": 5.0, "finance": 2.0, "other": 0.0, "total": 70.0}
    rows = []
    for label, scale in [("A", 1.0), ("B", 2.0)]:
        for o, a in amounts.items():
            rows.append({"quarter_end": Q, "rbi_state": "S", "rbi_district": label,
                         "occupation": o, "accounts": 1.0, "amount_cr": a * scale})
    return pd.DataFrame(rows)


def test_merged_config_adds_per_state():
    base = {"names": {"Goa": {"X": "North Goa"}}, "state_wide_labels": {"Delhi": ["NEW"]}}
    out = merged_config(base, {"names": {"Goa": {"Y": "South Goa"}, "Bihar": {"Z": "Patna"}},
                               "state_wide_labels": {"Delhi": ["DELHI"]}})
    assert out["names"]["Goa"] == {"X": "North Goa", "Y": "South Goa"}
    assert out["names"]["Bihar"] == {"Z": "Patna"}
    assert out["state_wide_labels"]["Delhi"] == ["NEW", "DELHI"]
    assert base["names"]["Goa"] == {"X": "North Goa"}           # the base is left alone


def test_to_sectors_groups_occupations():
    s = to_sectors(_occ())
    a = s[s.rbi_district == "A"].set_index("sector").amount_cr
    assert a["services"] == pytest.approx(10.0)    # transport, professional, trade, finance
    assert a["all"] == 70.0 and a["personal"] == 30.0
    assert set(s.sector) == {"agriculture", "industry", "services", "personal", "other",
                            "all"}


def test_build_sector_panel_shares_a_label():
    xw = pd.DataFrame({"rbi_name": ["A", "B", "B"], "rbi_state": "S",
                       "valid_from": pd.Timestamp("2002-03-31"), "valid_to": pd.NaT,
                       "district_id": [1, 2, 3], "weight": [1.0, 0.75, 0.25],
                       "match_type": ["exact", "split", "split"]})
    master = pd.DataFrame({"district_id": [1, 2, 3, 4], "split_flag": False})
    p = build_sector_panel(_occ(), xw, master).set_index(["district_id", "sector"])
    assert p.amount_cr[(2, "all")] == pytest.approx(105.0)
    assert p.imputed_share[(3, "agriculture")] == pytest.approx(1.0)
    assert np.isnan(p.amount_cr[(4, "all")])                     # no label: a null row
    assert len(p) == 4 * 6 and (p.basis == "utilisation").all()
