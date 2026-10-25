import pandas as pd

from cri.stress import scenarios as sc

# a line of districts 1-2-3-4-5 with a branch 3-6
EDGES = pd.DataFrame({"a": [1, 2, 3, 4, 3], "b": [2, 3, 4, 5, 6]})
SCORE = pd.Series({1: 0.9, 2: 0.5, 3: 0.4, 4: 0.8, 5: 0.7, 6: 0.95})


def test_grow_region_follows_the_most_hazardous_neighbour():
    adj = sc.adjacency_from_edges(EDGES)
    assert sc.grow_region(1, 3, adj, SCORE) == [1, 2, 3]
    assert sc.grow_region(3, 3, adj, SCORE) == [3, 6, 4]
    assert sc.grow_region(1, 10, adj, SCORE) == [1, 2, 3, 6, 4, 5]  # stops when exhausted


def test_shift_matches_intensity_to_hazard_rank():
    adj = sc.adjacency_from_edges(EDGES)
    src = pd.DataFrame({"district_id": [10, 11], "intensity": [0.1, 0.4],
                        "heavily_treated": [False, True]})
    districts = pd.DataFrame({"district_id": [1, 2, 3, 4, 5, 6],
                              "state": ["A", "A", "B", "B", "B", "B"]})
    out = sc.shift(src, "B", districts, adj, SCORE)
    # seed is B's most hazardous district (6); its best neighbour is 3
    assert out.district_id.tolist() == [6, 3]
    assert out.intensity.tolist() == [0.4, 0.1] and out.heavily_treated.tolist() == [True, False]


def test_scale_caps_floods_and_flags_extrapolation():
    src = pd.DataFrame({"district_id": [1, 2], "intensity": [0.5, 0.8],
                        "heavily_treated": [True, True]})
    out = sc.scale(src, 1.5, "flood", observed_max=0.9)
    assert out.intensity.tolist() == [0.75, 1.0]
    assert out.beyond_observed.tolist() == [False, True]


def test_compound_keeps_the_harder_hit():
    a = pd.DataFrame({"district_id": [1, 2], "intensity": [100.0, 60.0],
                      "heavily_treated": [True, False]})
    b = pd.DataFrame({"district_id": [2, 3], "intensity": [0.3, 0.1],
                      "heavily_treated": [True, False]})
    out = sc.compound(a, b).set_index("district_id")
    assert list(out.index) == [1, 2, 3]
    assert out.loc[2, "intensity"] == 0.3  # heavily treated by the flood, not by the storm
