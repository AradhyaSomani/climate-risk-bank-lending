import numpy as np
import pandas as pd

from cri.events import catalogue as cat

FLOOD = {"treated_share": 0.05, "heavy_share": 0.15, "partial_share": 0.01}
CYC = {"treated_km": 100, "treated_grade": "SCS", "heavy_km": 50, "heavy_grade": "VSCS",
       "partial_km": 200, "partial_grade": "CS"}


def test_quarter_end():
    assert cat.quarter_end("2019-05-03 04:00") == pd.Timestamp("2019-06-30")
    assert cat.quarter_end("2018-08-08") == pd.Timestamp("2018-09-30")


def test_flood_rules_with_state_restriction_and_exclusion_zone():
    fp = pd.DataFrame({"district_id": [1, 2, 3, 4], "flooded_share": [0.3, 0.06, 0.02, 0.4],
                       "flooded_built_share": np.nan})
    in_states = pd.Series({1: True, 2: True, 3: True, 4: False})
    rows = cat.flood_rows("FL-X", fp, FLOOD, in_states)
    assert rows.treated.tolist() == [True, True, False, False]  # 4 is in another state
    assert rows.heavily_treated.tolist() == [True, False, False, False]
    edges = pd.DataFrame({"a": [1, 2], "b": [5, 6], "weight": 1.0})
    out = cat.finish(rows, edges, use_neighbours=True).set_index("district_id")
    # 3 partly flooded, 4 flooded out of state, 5 and 6 neighbours of treated districts
    assert set(out.index[out.excluded]) == {3, 4, 5, 6}
    assert not (out.treated & out.excluded).any()


def test_cyclone_rules():
    exp = pd.DataFrame({"district_id": [1, 2, 3, 4], "track_dist_km": [0, 80, 150, 40],
                        "wind_kt_closest": [100, 60, 40, 30],
                        "grade_closest": ["ESCS", "SCS", "CS", "DD"]})
    rows = cat.cyclone_rows("CY-X", exp, CYC)
    assert rows.treated.tolist() == [True, True, False, False]
    assert rows.heavily_treated.tolist() == [True, False, False, False]
    out = cat.finish(rows, None, use_neighbours=False)
    assert out.set_index("district_id").excluded.to_dict() == {1: False, 2: False, 3: True}
