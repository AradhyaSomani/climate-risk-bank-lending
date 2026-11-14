"""Phase 0 E: event list check and simulation-based power check, blind to post-event outcomes.

For each main event (configs/events.yaml `main_events`) and outcome (log credit, log
deposits, all banks and sectors), this asks how large an effect on the pre-registered
summary (the mean of b(0) to b(3), docs/00_hypotheses.md section 3) the design could detect,
using the real panel noise and the real number of treated districts.

No post-event outcome is used. The event's own impact date is replaced by pseudo impact
quarters whose window (quarters -8 to +3) ends before the real impact quarter, and every
district's quarters from the impact of any catalogue event that treated or excluded it to 12
quarters after are kept out (`blocked`). In each pseudo window:

1. Matching as pre-registered: for each treated district the five nearest controls (with
   replacement) by Mahalanobis distance on the mean log level and mean growth over quarters
   -8 to -1, log population, urban share and agricultural-worker share.
2. The estimate is the matched difference in (mean of quarters 0 to 3 minus quarter -1).
   With district and quarter fixed effects and a dummy for every event quarter, the stacked
   regression gives exactly this number for one event.
3. Randomization inference as pre-registered: treatment reassigned at random among the
   event's eligible districts in its states (`draws` times); the 5% two-sided critical value
   is the 95th percentile of the absolute reassigned estimates.

A planted effect d (in log points) moves only post-period outcomes of treated districts, so
it leaves the matching unchanged and shifts the estimate by exactly d. Power at d is the
share of reassigned estimates (stand-ins for the real set's noise) with |estimate + d| above
the critical value, averaged over pseudo windows. The minimum detectable effect (MDE) is the
smallest effect with 80% power, against a fall or a rise, whichever is larger. The real
treated set's own placebo estimates at the pseudo dates are kept as a check: if they spread
more than the reassigned ones, the MDE is too optimistic.

The pooled estimate per hazard type averages the events that pass the pre-registered
exclusion rules, weighted by treated districts, with a random pseudo window per event.

    python -m cri.events.power            # writes docs/eval_reports/power_check.{md,csv}
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config

log = logging.getLogger(__name__)

REPORT = "docs/eval_reports/power_check.md"


@dataclass
class Window:
    """One pseudo impact quarter: estimates of the real treated set and of reassigned sets."""

    tau: pd.Timestamp
    placebo: float
    null: np.ndarray
    null_all: np.ndarray | None = None   # reassigned among all eligible districts


def as_all(windows: list[Window]) -> list[Window]:
    """The same windows with the nationwide reassignment as their null."""
    return [Window(w.tau, w.placebo, w.null_all) for w in windows]


# ---------------------------------------------------------------------------- data

def log_outcome(panel: pd.DataFrame, measure: str, break_missing: bool) -> pd.DataFrame:
    """Wide table of log amount, all banks and sectors, on every calendar quarter (quarters
    RBI did not publish are all-missing rows). Non-positive amounts are missing, and so are
    series-break quarters when `break_missing` (the drafted rule)."""
    p = panel[(panel.measure == measure) & (panel.bank_group == "all") & (panel.sector == "all")]
    keep = p.amount_cr > 0
    if break_missing:
        keep &= ~p.series_break.astype(bool)
    wide = p.assign(y=np.log(p.amount_cr.where(keep))) \
        .pivot(index="quarter_end", columns="district_id", values="y").sort_index()
    cal = pd.date_range(wide.index.min(), wide.index.max(), freq="QE")
    return wide.reindex(cal)


def required(rows: pd.DataFrame, skip_unpublished: bool) -> pd.Series:
    """Per district: has a figure in every quarter of `rows` (a window), skipping quarters
    nobody has a figure for (RBI did not publish them) when `skip_unpublished`. Coverage
    only: whether a figure exists, never its value."""
    if skip_unpublished:
        rows = rows[rows.notna().any(axis=1)]
    return rows.notna().all()


def blocked_spans(events: pd.DataFrame, ed: pd.DataFrame, after: int) -> dict[int, list]:
    """Per district: (first, last) quarter-end of every span from the impact quarter of an
    event that treated or excluded it to `after` quarters later."""
    q0 = events.set_index("event_id").impact_quarter.map(pd.Timestamp)
    hit = ed[ed.treated | ed.excluded]
    spans: dict[int, list] = {}
    for eid, d in zip(hit.event_id, hit.district_id, strict=True):
        start = q0[eid]
        end = (start.to_period("Q") + after).end_time.normalize()
        spans.setdefault(int(d), []).append((start, end))
    return spans


def free(spans: dict[int, list], d: int, lo: pd.Timestamp, hi: pd.Timestamp) -> bool:
    """True if district d has no blocked span overlapping [lo, hi]."""
    return all(hi < s or lo > e for s, e in spans.get(d, []))


# ---------------------------------------------------------------------------- estimator

def covariates(y: np.ndarray, static: np.ndarray) -> np.ndarray:
    """Matching covariates from the pre-period rows of y (quarters -8..-1, districts in
    columns): mean log level, mean quarterly growth, then the static columns."""
    pre = y[:8]
    growth = np.nanmean(np.diff(pre, axis=0), axis=0)
    return np.column_stack([np.nanmean(pre, axis=0), growth, static])


def match_weights(xt: np.ndarray, xc: np.ndarray, k: int, vi: np.ndarray) -> np.ndarray:
    """Weight of each control: how many times it is among a treated district's k nearest
    (Mahalanobis, with replacement), divided by k. Sums to the number of treated."""
    diff = xt[:, None, :] - xc[None, :, :]
    dist = np.einsum("tcj,jk,tck->tc", diff, vi, diff)
    k = min(k, xc.shape[0])
    nearest = np.argpartition(dist, k - 1, axis=1)[:, :k]
    return np.bincount(nearest.ravel(), minlength=xc.shape[0]) / k


def did_summary(yt: np.ndarray, yc: np.ndarray, w: np.ndarray) -> float:
    """Mean over quarters 0..3 of the treated-minus-matched-control gap, minus the gap at
    quarter -1. Rows are quarters -8..+3; a quarter nobody has (unpublished) is left out of
    the mean."""
    gap = yt.mean(axis=1) - (yc @ w) / w.sum()
    return float(np.nanmean(gap[8:12]) - gap[7])


def estimate(y: np.ndarray, static: np.ndarray, treated: np.ndarray, controls: np.ndarray,
             k: int, vi: np.ndarray) -> float:
    """y: quarters -8..+3 by district (columns indexed by the integer arrays)."""
    x = covariates(y, static)
    w = match_weights(x[treated], x[controls], k, vi)
    return did_summary(y[:, treated], y[:, controls], w)


# ---------------------------------------------------------------------------- one event

def pseudo_windows(e: pd.Series, treated: list[int], pool: list[int], controls: list[int],
                   y: pd.DataFrame, static: pd.DataFrame, spans: dict, cfg: dict,
                   skip_unpublished: bool, rng: np.random.Generator) -> list[Window]:
    """Pseudo impact quarters before the real one, each with the real set's placebo
    estimate and `draws` reassigned estimates. `pool`: districts treatment can be reassigned
    among (treated plus eligible same-state districts); `controls`: the control pool."""
    quarters = list(y.index)
    t0 = pd.Timestamp(e.impact_quarter)
    out = []
    for i in range(8, len(quarters) - 3):
        lo, hi = quarters[i - 8], quarters[i + 3]
        if hi >= t0:
            break
        rows = y.iloc[i - 8:i + 4]
        if rows.iloc[7].isna().all() or rows.iloc[8:12].isna().all().all():
            continue                  # no quarter -1, or none of 0..3, was published
        complete = required(rows, skip_unpublished)

        def ok(ds, rows=rows, complete=complete, lo=lo, hi=hi):
            return [d for d in ds if d in rows.columns and complete[d] and free(spans, d, lo, hi)]

        tr = ok(treated)
        if len(tr) < len(treated):    # the real set must be whole in a pseudo window
            continue
        pl, ct = ok(pool), ok(controls)
        if len(ct) < cfg["min_controls"]:
            continue
        cols = sorted(set(pl) | set(ct))
        pos = {d: j for j, d in enumerate(cols)}
        ya = rows[cols].to_numpy()
        st = static.loc[cols].to_numpy()
        x = covariates(ya, st)
        vi = np.linalg.pinv(np.cov(x, rowvar=False))
        t_idx = np.array([pos[d] for d in tr])
        c_idx = np.array([pos[d] for d in ct])
        placebo = estimate(ya, st, t_idx, c_idx, cfg["k_controls"], vi)
        p_idx = np.array([pos[d] for d in pl])
        a_idx = np.union1d(t_idx, c_idx)
        null = np.empty(cfg["draws"])
        null_all = np.empty(cfg["draws"])
        for r in range(cfg["draws"]):
            s = rng.choice(p_idx, size=len(t_idx), replace=False)
            null[r] = estimate(ya, st, s, np.setdiff1d(c_idx, s), cfg["k_controls"], vi)
            s = rng.choice(a_idx, size=len(t_idx), replace=False)
            null_all[r] = estimate(ya, st, s, np.setdiff1d(a_idx, s), cfg["k_controls"], vi)
        out.append(Window(quarters[i], placebo, null, null_all))
    return out


def power_curve(windows: list[Window], effects: np.ndarray, alpha: float) -> np.ndarray:
    """Power at each effect (log points), averaged over windows; the null draws stand in
    for the real set's noise."""
    if not windows:
        return np.full(len(effects), np.nan)
    pw = []
    for w in windows:
        crit = np.quantile(np.abs(w.null), 1 - alpha)
        pw.append((np.abs(w.null[None, :] + effects[:, None]) > crit).mean(axis=1))
    return np.mean(pw, axis=0)


def placebo_rejections(windows: list[Window], alpha: float) -> float:
    """Share of pseudo windows where the real treated set, with no effect planted, is
    rejected: the test's size for this set. Near alpha if randomization is a fair model of
    its noise; above it if the set's districts move together more than random sets do."""
    if not windows:
        return np.nan
    return float(np.mean([abs(w.placebo) > np.quantile(np.abs(w.null), 1 - alpha)
                          for w in windows]))


def placebo_rmse(windows: list[Window]) -> float:
    """Root mean square of the real treated set's estimates at the pseudo dates, where the
    true effect is zero: its bias and noise together, without their sign."""
    if not windows:
        return np.nan
    return float(np.sqrt(np.mean([w.placebo ** 2 for w in windows])))


def mde_normal(rmse: float, alpha: float, power: float) -> float:
    """MDE (log points) for an estimate with this error, normal approximation."""
    from statistics import NormalDist

    z = NormalDist().inv_cdf
    return (z(1 - alpha / 2) + z(power)) * rmse


def mde(windows: list[Window], grid: np.ndarray, alpha: float, power: float) -> float:
    """Smallest effect (log points) with the target power against a fall and against a
    rise; the larger of the two. NaN without windows, inf if nothing on the grid."""
    if not windows:
        return np.nan
    worst = 0.0
    for sign in (-1, 1):
        p = power_curve(windows, sign * grid, alpha)
        hit = np.flatnonzero(p >= power)
        if not len(hit):
            return np.inf
        worst = max(worst, grid[hit[0]])
    return worst


def pooled_windows(per_event: dict[str, list[Window]], weights: dict[str, int], n: int,
                   rng: np.random.Generator) -> list[Window]:
    """`n` pooled replicates: a random window per event, estimates averaged with the
    treated-district weights. Returned as one Window so the same power code applies; its
    `placebo` is the root mean square of the pooled placebo estimates."""
    ev = [e for e in per_event if per_event[e]]
    if not ev:
        return []
    w = np.array([weights[e] for e in ev], dtype=float)
    w /= w.sum()
    null = np.zeros(n)
    null_all = np.zeros(n)
    placebo = np.zeros(n)
    for e, we in zip(ev, w, strict=True):
        wins = per_event[e]
        pick = rng.integers(len(wins), size=n)
        draw = rng.integers(len(wins[0].null), size=n)
        null += we * np.array([wins[p].null[r] for p, r in zip(pick, draw, strict=True)])
        null_all += we * np.array([wins[p].null_all[r] for p, r in zip(pick, draw, strict=True)])
        placebo += we * np.array([wins[p].placebo for p in pick])
    return [Window(pd.NaT, float(np.sqrt(np.mean(placebo ** 2))), null, null_all)]


# ---------------------------------------------------------------------------- the check

def event_sets(eid: str, events: pd.DataFrame, ed: pd.DataFrame, states_of: pd.Series
               ) -> tuple[list[int], set[int], list[int]]:
    """Treated districts, treated-or-excluded districts, and the reassignment pool (treated
    plus same-state districts outside the exclusion zone)."""
    e = events.set_index("event_id").loc[eid]
    d = ed[ed.event_id == eid]
    tr = sorted(d.district_id[d.treated])
    out = set(d.district_id[d.treated | d.excluded])
    states = set(str(e.states).split(";"))
    pool = sorted(set(tr) | {c for c in states_of.index[states_of.isin(states)] if c not in out})
    return tr, out, pool


def event_table(events: pd.DataFrame, ed: pd.DataFrame, states_of: pd.Series,
                y: dict[str, dict[str, pd.DataFrame]], rules: dict, main: list[str]
                ) -> pd.DataFrame:
    """Phase 0 E counts per main event, from hazard data and data coverage only: treated,
    heavily treated, excluded, same-state districts outside the exclusion zone (clearly
    unaffected nearby), and under each rule the treated districts and eligible controls with
    the required figures over quarters -8..+3, plus quarters of data before the event."""
    ev = events.set_index("event_id")
    others_all = ed[ed.event_id.isin(main) & ed.treated]
    rows = []
    for eid in main:
        e = ev.loc[eid]
        d = ed[ed.event_id == eid]
        tr, out, pool = event_sets(eid, events, ed, states_of)
        t0 = pd.Timestamp(e.impact_quarter)
        # districts treated by another main event whose impact falls in this window
        others = others_all[others_all.event_id != eid]
        q_other = pd.to_datetime(others.event_id.map(ev.impact_quarter))
        gap = (q_other.dt.year * 4 + q_other.dt.quarter) - (t0.year * 4 + t0.quarter)
        busy = set(others.district_id[(gap >= -8) & (gap <= 12)])
        row = {"event_id": eid, "hazard_type": e.hazard_type, "impact_quarter": t0.date(),
               "treated": len(tr), "heavily_treated": int(d.heavily_treated.sum()),
               "excluded": int(d.excluded.sum()), "same_state_unaffected": len(pool) - len(tr)}
        for rule, spec in rules.items():
            for m, ym in y[rule].items():
                i = ym.index.get_indexer([t0])[0]
                if i < 8 or i + 3 >= len(ym):
                    row[f"treated_complete_{m}_{rule}"] = row[f"controls_complete_{m}_{rule}"] = 0
                    continue
                complete = required(ym.iloc[i - 8:i + 4], spec["skip_unpublished"])
                ctrl = [c for c in ym.columns if c not in out and c not in busy and complete[c]]
                row[f"controls_complete_{m}_{rule}"] = len(ctrl)
                row[f"treated_complete_{m}_{rule}"] = int(sum(bool(complete.get(t, False))
                                                              for t in tr))
        first = y[next(iter(rules))]["credit"]
        row["pre_event_quarters"] = int((first.index[first.notna().any(axis=1)] < t0).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def eligible(table: pd.DataFrame, eid: str, m: str, rule: str, cfg: dict) -> bool:
    """The pre-registered event exclusion rules: at least `min_treated` treated districts,
    all of them with the required figures, and `min_controls` eligible controls."""
    r = table.set_index("event_id").loc[eid]
    return (r.treated >= cfg["min_treated"]
            and r[f"treated_complete_{m}_{rule}"] == r.treated
            and r[f"controls_complete_{m}_{rule}"] >= cfg["min_controls"])


def run(panel: pd.DataFrame, events: pd.DataFrame, ed: pd.DataFrame, master: pd.DataFrame,
        controls: pd.DataFrame, cfg: dict, main: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Event table and power results. Per-event MDEs use the proposed rule (pseudo windows
    hardly differ between rules); the pooled MDE is given for each rule's eligible events."""
    rng = np.random.default_rng(cfg["seed"])
    alpha, target = cfg["alpha"], cfg["power"]
    grid = np.arange(0.0025, cfg["grid_max"] + 1e-9, 0.0025)
    effects = np.log1p(np.array(cfg["effects"]))
    rules = cfg["rules"]
    spans = blocked_spans(events, ed, cfg["blocked_quarters"])
    ag = controls.groupby("district_id").ag_worker_share_2011.first()
    static = master.set_index("district_id")[["population", "urban_share"]].assign(
        population=lambda m: np.log(m.population), ag=ag).fillna(0.0)
    states_of = master.set_index("district_id").state
    y = {rule: {m: log_outcome(panel, m, spec["series_break_missing"]) for m in cfg["measures"]}
         for rule, spec in rules.items()}
    table = event_table(events, ed, states_of, y, rules, main)
    ev = events.set_index("event_id")
    use = cfg["power_rule"]
    rows, per = [], {}

    def stats(wins, rmse):
        pc = power_curve(wins, -effects, alpha)
        return {**{f"power_{int(round(x * 100))}pct": p
                   for x, p in zip(cfg["effects"], pc, strict=True)},
                "mde": float(np.expm1(mde(wins, grid, alpha, target))),
                "mde_all_pool": float(np.expm1(mde(as_all(wins), grid, alpha, target))),
                "placebo_rmse": rmse,
                "mde_placebo": float(np.expm1(mde_normal(rmse, alpha, target))),
                "placebo_rejections": placebo_rejections(wins, alpha),
                "placebo_rejections_all_pool": placebo_rejections(as_all(wins), alpha)}

    for m in cfg["measures"]:
        for eid in main:
            tr, out, pool = event_sets(eid, events, ed, states_of)
            ctrl = sorted(c for c in states_of.index if c not in out)
            wins = pseudo_windows(ev.loc[eid].rename(eid), tr, pool, ctrl, y[use][m], static,
                                  spans, cfg, rules[use]["skip_unpublished"], rng)
            per[(m, eid)] = wins
            rows.append({
                "measure": m, "event_id": eid, "hazard_type": ev.loc[eid, "hazard_type"],
                "treated": len(tr), "ri_pool": len(pool),
                "ri_assignments": comb(len(pool), len(tr)) if tr else 0,
                "pseudo_windows": len(wins),
                "first_window": wins[0].tau.date() if wins else None,
                "last_window": wins[-1].tau.date() if wins else None,
                "null_sd": float(np.mean([w.null.std() for w in wins])) if wins else np.nan,
                **stats(wins, placebo_rmse(wins))})
    for rule in rules:
        for m in cfg["measures"]:
            for hz in ["flood", "cyclone"]:
                ok = [eid for eid in main if ev.loc[eid, "hazard_type"] == hz
                      and eligible(table, eid, m, rule, cfg) and per[(m, eid)]]
                n_tr = {e: int(table.set_index("event_id").loc[e, "treated"]) for e in ok}
                wins = pooled_windows({e: per[(m, e)] for e in ok}, n_tr,
                                      cfg["pooled_draws"], rng)
                rows.append({"measure": m, "event_id": f"pooled {hz}s ({rule} rule)",
                             "hazard_type": hz, "rule": rule, "treated": sum(n_tr.values()),
                             "pooled_events": "; ".join(ok),
                             "null_sd": wins[0].null.std() if wins else np.nan,
                             **stats(wins, wins[0].placebo if wins else np.nan)})
    res = pd.DataFrame(rows)
    res["mde_worst"] = res[["mde", "mde_all_pool", "mde_placebo"]].max(axis=1)
    res["passes"] = res.mde <= cfg["mde_pass"]
    res["passes_worst"] = res.mde_worst <= cfg["mde_pass"]
    return table, res


# ---------------------------------------------------------------------------- report

def _pct(x) -> str:
    if pd.isna(x):
        return "n/a"
    return "> 30%" if np.isinf(x) else f"{100 * x:.1f}%"


def _num(x, fmt="{:.2f}") -> str:
    return "n/a" if pd.isna(x) else fmt.format(x)


def report(table: pd.DataFrame, res: pd.DataFrame, cfg: dict, main: list[str]) -> str:
    eff = [int(round(x * 100)) for x in cfg["effects"]]
    rules = list(cfg["rules"])
    L = [
        "# Phase 0 E: event list and power check",
        "",
        "Generated by `python -m cri.events.power` from `configs/power.yaml`. It is blind to",
        "post-event outcomes. Every estimate uses pseudo impact quarters whose window (-8 to +3)",
        "ends before the real one. No district contributes quarters from the impact of any",
        "catalogue event that treated or excluded it to 12 quarters after. The method is in the",
        "module docstring.",
        "",
        "Two completeness rules are compared (`rules` in the config):",
        "",
    ]
    for rule, spec in cfg["rules"].items():
        L.append(f"- **{rule}**: {spec['text']}")
    L += ["", "## Events", "",
          "Counts come from the hazard tables and from data coverage only (whether a figure",
          "exists). *Same-state unaffected* means districts of the event's states outside the",
          "treated set and the exclusion zone. *Complete* means districts with every required",
          "figure over quarters -8 to +3 around the real impact quarter; controls are also not",
          "treated by another main event within the window.",
          "",
          "| Event | Impact quarter | Treated | Heavily treated | Excluded | Same-state unaffected"
          " | " + " | ".join(f"Treated / controls complete, credit ({r})" for r in rules)
          + " | Quarters before |",
          "| --- | --- | --- | --- | --- | --- | " + " | ".join("---" for _ in rules) + " | --- |"]
    for r in table.to_dict("records"):
        comp = " | ".join(f"{r[f'treated_complete_credit_{u}']} / "
                          f"{r[f'controls_complete_credit_{u}']}" for u in rules)
        L.append(f"| {r['event_id']} | {r['impact_quarter']} | {r['treated']} | "
                 f"{r['heavily_treated']} | {r['excluded']} | {r['same_state_unaffected']} | "
                 f"{comp} | {r['pre_event_quarters']} |")
    L += ["", "## Minimum detectable effects per event", "",
          "The pre-registered test is two-sided randomization inference (RI) at 5%: treatment"
          " reassigned among the event's eligible districts of the same states,"
          f" {cfg['draws']} reassignments per pseudo window, on the mean of quarters 0 to 3. The"
          " MDE is the smallest effect with 80% power, against a fall or a rise. An event"
          f" passes if its MDE is {100 * cfg['mde_pass']:.0f}% or less (pre-registration"
          " section 6). Two checks sit next to it:", "",
          "- **RI, all districts**: treatment reassigned among all eligible districts in India,"
          " for events whose states have few districts outside the exclusion zone.",
          "- **Placebo dates**: the real treated set's own estimates at the pseudo dates, where"
          " the true effect is zero. Their root mean square (bias and noise together) gives a"
          " normal-approximation MDE. *Rejections* is the share of pseudo windows where the RI"
          " test rejects the real set with no effect. It should be near 5%; above that, the"
          " RI test is too optimistic for this set.", "",
          "The **largest** of the three MDEs is the honest one to plan with.", ""]
    for m in cfg["measures"]:
        sub = res[(res.measure == m) & res.event_id.isin(main)].to_dict("records")
        L += [f"### Log {m}", "",
              "| Event | Treated | Same-state pool (assignments) | Pseudo windows | "
              + " | ".join(f"Power at -{e}%" for e in eff) + " |",
              "| --- | --- | --- | --- | " + " | ".join("---" for _ in eff) + " |"]
        for r in sub:
            pw = " | ".join(_num(r[f"power_{e}pct"]) for e in eff)
            L.append(f"| {r['event_id']} | {r['treated']} | {int(r['ri_pool'])} "
                     f"({int(r['ri_assignments']):,}) | {int(r['pseudo_windows'])} | {pw} |")
        L += ["", "| Event | MDE, RI same state | Rejections | MDE, RI all districts | "
              "Rejections | MDE, placebo dates | Largest MDE | Passes as drafted | "
              "Passes on the largest |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in sub:
            L.append(f"| {r['event_id']} | {_pct(r['mde'])} | {_num(r['placebo_rejections'])} | "
                     f"{_pct(r['mde_all_pool'])} | {_num(r['placebo_rejections_all_pool'])} | "
                     f"{_pct(r['mde_placebo'])} | {_pct(r['mde_worst'])} | "
                     f"{'yes' if r['passes'] else 'no'} | "
                     f"{'yes' if r['passes_worst'] else 'no'} |")
        L.append("")
    L += ["## Pooled minimum detectable effects", "",
          "The pooled estimate per hazard type is the treated-weighted mean over the events that",
          "pass the pre-registered exclusion rules (at least 3 treated districts, all with the",
          "required figures, and at least 10 eligible controls) under each completeness rule.",
          "",
          "| Outcome | Hazard | Rule | Events | Treated | "
          + " | ".join(f"Power at -{e}%" for e in eff)
          + " | MDE, RI same state | MDE, RI all districts | MDE, placebo dates |",
          "| --- | --- | --- | --- | --- | " + " | ".join("---" for _ in eff)
          + " | --- | --- | --- |"]
    for r in res[~res.event_id.isin(main)].to_dict("records"):
        pw = " | ".join(_num(r[f"power_{e}pct"]) for e in eff)
        L.append(f"| {r['measure']} | {r['hazard_type']} | {r['rule']} | "
                 f"{r['pooled_events'] or 'none'} | {r['treated']} | {pw} | {_pct(r['mde'])} | "
                 f"{_pct(r['mde_all_pool'])} | {_pct(r['mde_placebo'])} |")
    L += ["", "## Gate", "",
          f"The gate needs {cfg['min_passing_events']} events that pass on log credit and meet"
          " the exclusion rules.", ""]
    for rule in rules:
        for col, label in [("passes", "the drafted RI MDE"), ("passes_worst", "the largest MDE")]:
            ok = [e for e in main if eligible(table, e, "credit", rule, cfg)
                  and bool(res[(res.measure == "credit") & (res.event_id == e)][col].iloc[0])]
            L.append(f"- {rule} completeness rule, judged on {label}: {len(ok)} of {len(main)}"
                     f" ({', '.join(ok) or 'none'}).")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = config.load("power")
    main_events = config.load("events")["main_events"]
    proc = config.path("processed")
    table, res = run(pd.read_parquet(proc / "panel_credit_deposit.parquet"),
                     pd.read_parquet(proc / "events.parquet"),
                     pd.read_parquet(proc / "event_district.parquet"),
                     pd.read_parquet(config.path("district_geometry.preferred"),
                                     columns=["district_id", "state", "population",
                                              "urban_share"]),
                     pd.read_parquet(proc / "controls_district_quarter.parquet",
                                     columns=["district_id", "ag_worker_share_2011"]),
                     cfg, main_events)
    out = config.REPO_ROOT / REPORT
    out.write_text(report(table, res, cfg, main_events) + "\n")
    res.to_csv(Path(out).with_suffix(".csv"), index=False)
    log.info("power check: %s", out)
    print(out)


if __name__ == "__main__":
    main()
