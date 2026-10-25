"""Do neighbouring districts tell us more about a district's lending after a shock than a
simple spatial lag? (Phase 2B-D)

Target: quarterly growth of log credit per district (bank group and sector "all" from B's
panel, contract C2). Shocks: the treatment flags of the event catalogue (contract C4), at the
impact quarter and the three quarters after it.

- H0, no graph: ridge regression on the district's own four lags, its own shock terms and
  quarter-of-year dummies.
- H1, spatial lag: H0 plus the row-standardised neighbour averages of last quarter's growth
  and of the shock terms.
- H2, graph model: a two-layer GraphSAGE-style network (own features plus the neighbour mean,
  written in plain PyTorch on the dense row-standardised adjacency) on the same inputs as H0.

Evaluation is leave-one-event-out: for each event, every quarter of its window is removed
from training (all districts, so no contemporaneous leak), the models are fitted on the
rest, and the error is measured on the event's treated districts in its window. The gate:
H2 must have lower RMSE than H1 on average over events.

Leakage check (Evaluation B5): the same evaluation on a shuffled target. No model should then
beat predicting the training mean, which every run also reports as `naive_train_mean`.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

LAGS = 4
WINDOW = 4  # impact quarter and the three after it


def credit_growth(panel: pd.DataFrame, measure: str = "credit") -> pd.DataFrame:
    """Wide (quarter_end x district_id) quarterly change in log amount; series breaks -> NaN."""
    p = panel[(panel.measure == measure) & (panel.bank_group == "all") & (panel.sector == "all")]
    amt = p.pivot_table(index="quarter_end", columns="district_id", values="amount_cr")
    brk = p.pivot_table(index="quarter_end", columns="district_id", values="series_break",
                        aggfunc="max").reindex_like(amt).fillna(False).astype(bool)
    g = np.log(amt.where(amt > 0)).diff()
    return g.mask(brk).sort_index()


def shock_matrix(events: pd.DataFrame, event_district: pd.DataFrame, quarters, ids
                 ) -> pd.DataFrame:
    """1 where a district is treated by an event whose impact quarter is that quarter."""
    ed = event_district[event_district.treated].merge(
        events[["event_id", "impact_quarter"]], on="event_id")
    s = pd.DataFrame(0.0, index=pd.Index(quarters, name="quarter_end"), columns=ids)
    for r in ed.itertuples():
        q = pd.Timestamp(r.impact_quarter)
        if q in s.index and r.district_id in s.columns:
            s.loc[q, r.district_id] = 1.0
    return s


def design(y: pd.DataFrame, s: pd.DataFrame, w: np.ndarray) -> pd.DataFrame:
    """Long table, one row per (quarter, district), with every input the three models use.

    `w` is the row-standardised adjacency in the column order of `y`."""
    yv, sv = y.to_numpy(), s.reindex_like(y).fillna(0).to_numpy()
    T, N = yv.shape
    ywl = np.nan_to_num(yv) @ w.T  # neighbour mean of growth (NaN counted as 0)
    swl = sv @ w.T
    cols = {}
    for k in range(1, LAGS + 1):
        cols[f"y_lag{k}"] = np.vstack([np.full((k, N), np.nan), yv[:-k]])
    for k in range(WINDOW):
        cols[f"shock_l{k}"] = np.vstack([np.zeros((k, N)), sv[: T - k]])
        cols[f"w_shock_l{k}"] = np.vstack([np.zeros((k, N)), swl[: T - k]])
    cols["w_y_lag1"] = np.vstack([np.full((1, N), np.nan), ywl[:-1]])
    out = pd.DataFrame({k: v.ravel() for k, v in cols.items()})
    out["y"] = yv.ravel()
    out["t"] = np.repeat(np.arange(T), N)
    out["node"] = np.tile(np.arange(N), T)
    out["quarter_end"] = np.repeat(y.index.to_numpy(), N)
    out["district_id"] = np.tile(y.columns.to_numpy(), T)
    q = pd.DatetimeIndex(out.quarter_end).quarter
    for k in (2, 3, 4):
        out[f"q{k}"] = (q == k).astype(float)
    return out


MODELS = ["h0_no_graph", "h1_spatial_lag", "h2_graph_conv"]
OWN = [f"y_lag{k}" for k in range(1, LAGS + 1)] + [f"shock_l{k}" for k in range(WINDOW)] + [
    "q2", "q3", "q4"]
SPATIAL = ["w_y_lag1"] + [f"w_shock_l{k}" for k in range(WINDOW)]


def fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float = 1.0) -> np.ndarray:
    xa = np.c_[np.ones(len(x)), x]
    reg = alpha * np.eye(xa.shape[1])
    reg[0, 0] = 0
    return np.linalg.solve(xa.T @ xa + reg, xa.T @ y)


def predict_ridge(beta: np.ndarray, x: np.ndarray) -> np.ndarray:
    return np.c_[np.ones(len(x)), x] @ beta


def fit_predict_graph(d: pd.DataFrame, train: np.ndarray, test: np.ndarray, w: np.ndarray,
                      hidden: int = 16, epochs: int = 300, lr: float = 0.01,
                      seed: int = 0) -> np.ndarray:
    """H2: two GraphSAGE-mean layers over each quarter's node features; returns test preds."""
    import torch
    from torch import nn

    torch.manual_seed(seed)
    T, N = int(d.t.max()) + 1, int(d.node.max()) + 1
    x = np.nan_to_num(d[OWN].to_numpy(dtype="float32")).reshape(T, N, len(OWN))
    mu, sd = x.reshape(-1, len(OWN)).mean(0), x.reshape(-1, len(OWN)).std(0) + 1e-6
    x = torch.from_numpy((x - mu) / sd)
    y = torch.from_numpy(np.nan_to_num(d.y.to_numpy(dtype="float32")).reshape(T, N))
    wt = torch.from_numpy(w.astype("float32"))
    tr = torch.from_numpy(train.reshape(T, N))
    te = test.reshape(T, N)

    class Sage(nn.Module):
        def __init__(self):
            super().__init__()
            self.s1, self.n1 = nn.Linear(len(OWN), hidden), nn.Linear(len(OWN), hidden, bias=False)
            self.s2, self.n2 = nn.Linear(hidden, 1), nn.Linear(hidden, 1, bias=False)

        def forward(self, x):  # x: (T, N, F)
            h = torch.relu(self.s1(x) + self.n1(wt @ x))
            return (self.s2(h) + self.n2(wt @ h)).squeeze(-1)

    m = Sage()
    opt = torch.optim.Adam(m.parameters(), lr=lr, weight_decay=1e-4)
    for _ in range(epochs):
        opt.zero_grad()
        loss = ((m(x) - y)[tr] ** 2).mean()
        loss.backward()
        opt.step()
    with torch.no_grad():
        return m(x).numpy()[te]


def leave_one_event_out(d: pd.DataFrame, events: pd.DataFrame, event_district: pd.DataFrame,
                        w: np.ndarray, graph_kwargs: dict | None = None,
                        targets: dict[str, set[int]] | None = None) -> pd.DataFrame:
    """RMSE of H0, H1 and H2 on each held-out event's treated districts in its window.

    `targets` replaces the treated districts as the test set (e.g. the ring of neighbours,
    for the Phase 3F spillover test)."""
    usable = d[OWN + SPATIAL + ["y"]].notna().all(axis=1).to_numpy()
    quarters = pd.DatetimeIndex(sorted(d.quarter_end.unique()))
    rows = []
    for ev in events.itertuples():
        q0 = pd.Timestamp(ev.impact_quarter)
        if q0 not in quarters:
            continue
        i0 = quarters.get_loc(q0)
        win = set(quarters[i0:i0 + WINDOW])
        in_win = d.quarter_end.isin(win).to_numpy()
        if targets is not None:
            treated = pd.Series(sorted(targets.get(ev.event_id, set())), dtype=int)
        else:
            treated = event_district[(event_district.event_id == ev.event_id)
                                     & event_district.treated].district_id
        test = in_win & d.district_id.isin(treated).to_numpy() & usable
        train = ~in_win & usable
        if test.sum() == 0 or train.sum() < 50:
            continue
        y_te = d.y.to_numpy()[test]
        res = {"event_id": ev.event_id, "n_test": int(test.sum()),
               "naive_train_mean": float(np.sqrt(np.mean((d.y.to_numpy()[train].mean()
                                                          - y_te) ** 2)))}
        for name, cols in (("h0_no_graph", OWN), ("h1_spatial_lag", OWN + SPATIAL)):
            beta = fit_ridge(d.loc[train, cols].to_numpy(), d.y.to_numpy()[train])
            pred = predict_ridge(beta, d.loc[test, cols].to_numpy())
            res[name] = float(np.sqrt(np.mean((pred - y_te) ** 2)))
        pred = fit_predict_graph(d, train, test, w, **(graph_kwargs or {}))
        res["h2_graph_conv"] = float(np.sqrt(np.mean((pred - y_te) ** 2)))
        rows.append(res)
    out = pd.DataFrame(rows)
    if len(out):
        mean = out[MODELS + ["naive_train_mean"]].mean().to_dict()
        out = pd.concat([out, pd.DataFrame([{"event_id": "mean",
                                             "n_test": int(out.n_test.sum()), **mean}])],
                        ignore_index=True)
    return out


def shuffled_target(d: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """The design with `y` permuted across the rows that have one. The inputs, lags included,
    stay as they were, so nothing in them can predict the new target."""
    out = d.copy()
    has = out.y.notna().to_numpy()
    out.loc[has, "y"] = np.random.default_rng(seed).permutation(out.y.to_numpy()[has])
    return out


def leakage_check(d: pd.DataFrame, events: pd.DataFrame, event_district: pd.DataFrame,
                  w: np.ndarray, graph_kwargs: dict | None = None, seed: int = 0,
                  tolerance: float = 0.05) -> pd.DataFrame:
    """Leave-one-event-out on a shuffled target. One row per model with its mean RMSE over
    events relative to the training-mean prediction; collapsed when the ratio is at least
    1 - `tolerance`, i.e. the model has no skill left."""
    res = leave_one_event_out(shuffled_target(d, seed), events, event_district, w,
                              graph_kwargs)
    mean = res[res.event_id == "mean"].iloc[0]
    out = pd.DataFrame({"model": MODELS, "rmse": [float(mean[m]) for m in MODELS]})
    out["naive_rmse"] = float(mean.naive_train_mean)
    out["ratio"] = out.rmse / out.naive_rmse
    out["collapsed"] = out.ratio >= 1 - tolerance
    return out
