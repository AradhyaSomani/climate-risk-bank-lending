import numpy as np
import pandas as pd

from cri.stress import event_generator as eg
from cri.stress.scenarios import adjacency_from_edges

RULES = {"flood": {"treated_share": 0.05},
         "cyclone": {"treated_km": 100, "treated_grade": "SCS"}}
REGIONS = {"flood": {"north": ["A"], "south": ["B"]}, "cyclone": {"coast": ["B"]}}


def toy_tables():
    flood = pd.DataFrame({
        "event_id": ["GFD-1", "GFD-1", "GFD-1", "GFD-2"], "source": "gfd",
        "district_id": [1, 2, 3, 3], "flooded_share": [0.3, 0.2, 0.06, 0.02],
        "flooded_km2": [300.0, 200.0, 600.0, 10.0],
    })
    cyc = pd.DataFrame({"event_id": ["IMD-1"], "district_id": [3], "track_dist_km": [20.0],
                        "wind_kt_closest": [90.0], "grade_closest": ["ESCS"]})
    state = pd.Series({1: "A", 2: "A", 3: "B", 4: "B"})
    return flood, cyc, state


def test_historical_footprints_assign_the_main_region():
    flood, cyc, state = toy_tables()
    h = eg.historical_footprints(flood, cyc, state, REGIONS, RULES)
    # GFD-1 has 500 km2 in A and 600 km2 in B: it belongs to the south; GFD-2 is below 5%
    ev = h.drop_duplicates("event_id").set_index("event_id")
    assert ev.region.to_dict() == {"GFD-1": "south", "IMD-1": "coast"}
    assert ev.loc["GFD-1", "size"] == 1100.0 and ev.loc["IMD-1", "size"] == 1.0


def test_tail_fits_only_with_enough_exceedances():
    rng = np.random.default_rng(0)
    assert not eg.fit_tail(rng.pareto(2, 50) + 1, 0.8, 30)["fitted"]
    fit = eg.fit_tail(rng.pareto(2, 1000) + 1, 0.8, 30)
    assert fit["fitted"] and fit["n_exceed"] >= 30 and fit["shape"] > 0


def test_simulated_rate_matches_the_poisson_rate():
    flood, cyc, state = toy_tables()
    hist = eg.historical_footprints(flood, cyc, state, REGIONS, RULES)
    rates = pd.DataFrame({"hazard_type": ["flood", "cyclone"], "region": ["south", "coast"],
                          "rate": [0.5, 0.2]})
    adj = adjacency_from_edges(pd.DataFrame({"a": [1, 2, 3], "b": [2, 3, 4]}))
    score = {"flood": pd.Series({1: .1, 2: .2, 3: .9, 4: .5}),
             "cyclone": pd.Series({3: .9, 4: .4})}
    region_d = {("flood", "south"): {3, 4}, ("cyclone", "coast"): {3, 4}}
    sim = eg.simulate(hist, rates, adj, score, region_d, {}, years=4000, seed=1)
    ev = sim.drop_duplicates("sim_event")
    rate = ev.groupby("hazard_type").size() / 4000
    assert abs(rate["flood"] - 0.5) < 0.05 and abs(rate["cyclone"] - 0.2) < 0.03
    # footprints stay inside their region and keep the source's number of districts
    assert set(sim.district_id) <= {3, 4}
    assert sim.groupby("sim_event").size().max() <= 2
