import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from cri.ml.graph import build, models


def squares():
    # a 3 x 1 strip of 10 km squares plus one square touching only at a corner, and one
    # island; the middle pair has a 50 m gap that the snap distance closes
    geoms = [shapely.box(0, 0, 10_000, 10_000), shapely.box(10_050, 0, 20_000, 10_000),
             shapely.box(20_000, 0, 30_000, 10_000), shapely.box(30_000, 10_000, 40_000, 20_000),
             shapely.box(100_000, 0, 110_000, 10_000)]
    return gpd.GeoDataFrame({"district_id": [1, 2, 3, 4, 5]}, geometry=geoms, crs="EPSG:7755")


def test_edges_queen_snap_and_weights():
    e = build.edges(squares(), snap_m=200)
    pairs = set(zip(e.a, e.b, strict=True))
    assert pairs == {(1, 2), (2, 3), (3, 4)}
    w = e.set_index(["a", "b"]).weight
    assert w[(2, 3)] == pytest.approx(10.0, rel=0.05)  # 10 km shared edge
    assert bool(e.set_index(["a", "b"]).corner_only[(3, 4)])
    g = build.to_graph(e, [1, 2, 3, 4, 5])
    wn = build.row_normalised(g)
    assert wn[4].sum() == 0 and wn[1].sum() == pytest.approx(1.0)
    assert g["edge_index"].shape == (2, 6)


def synthetic(n_side=6, T=40, spill=0.6, seed=0):
    """Grid of districts; a shock lowers growth in the hit district and, by `spill`, in its
    neighbours."""
    rng = np.random.default_rng(seed)
    n = n_side * n_side
    ids = np.arange(1, n + 1)
    w = np.zeros((n, n))
    for i in range(n):
        r, c = divmod(i, n_side)
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < n_side and 0 <= cc < n_side:
                w[i, rr * n_side + cc] = 1
    w = w / w.sum(1, keepdims=True)
    quarters = pd.date_range("2010-03-31", periods=T, freq="QE")
    events, ed = [], []
    shock = np.zeros((T, n))
    for k, t in enumerate(range(8, T - 4, 4)):
        hit = rng.choice(n, 3, replace=False)
        shock[t, hit] = 1
        events.append({"event_id": f"E{k}", "impact_quarter": quarters[t]})
        ed += [{"event_id": f"E{k}", "district_id": int(ids[h]), "treated": True} for h in hit]
    y = 0.02 + rng.normal(0, 0.005, (T, n)) - 0.05 * shock - spill * 0.05 * shock @ w.T
    return (pd.DataFrame(y, index=quarters, columns=ids), pd.DataFrame(events),
            pd.DataFrame(ed), w)


def test_spatial_lag_wins_when_shocks_spill_over():
    y, events, ed, w = synthetic()
    s = models.shock_matrix(events, ed, y.index, y.columns)
    assert s.to_numpy().sum() == len(ed)
    d = models.design(y, s, w)
    res = models.leave_one_event_out(d, events, ed, w, {"epochs": 150, "hidden": 8})
    mean = res[res.event_id == "mean"].iloc[0]
    assert len(res) > 3
    # the treated districts' own shock is in H0 already; spillover from treated neighbours
    # only H1 and H2 can see, so H1 must not be worse than H0
    assert mean.h1_spatial_lag <= mean.h0_no_graph + 1e-9
    assert np.isfinite(mean.h2_graph_conv)


def test_credit_growth_masks_series_breaks():
    q = pd.to_datetime(["2015-03-31", "2015-06-30", "2015-09-30"])
    panel = pd.DataFrame({"district_id": 1, "quarter_end": q, "bank_group": "all",
                          "measure": "credit", "sector": "all", "amount_cr": [100.0, 110.0, 200.0],
                          "series_break": [False, False, True]})
    g = models.credit_growth(panel)[1]
    assert np.isnan(g.iloc[0]) and g.iloc[1] == pytest.approx(np.log(1.1))
    assert np.isnan(g.iloc[2])
