"""Phase 3F: do neighbours of treated districts move too? (spillover check)

For each event, districts are put in rings by distance on the district graph: ring 0 =
treated, ring 1 = neighbours of treated districts, ring 2 = their neighbours. Controls are the
districts in none of these and not otherwise excluded for that event.

1. Ring difference-in-differences: change in mean log credit (impact quarter to quarter
   +3, against quarters -8 to -1) in ring 1 and ring 2 minus the same change in controls,
   with a bootstrap interval over districts. If ring 1 moves, the control pool would be
   contaminated without the exclusion zone.
2. Graph test: whether the Phase 2B-D graph model (H2) predicts ring-1 districts' growth
   better than the spatial-lag model (H1), leave-one-event-out.

Needs B's panel (contract C2) and the event catalogue (C4).

    python -m cri.events.spillover
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

from cri import config

log = logging.getLogger(__name__)


def rings(treated: set[int], adjacency: dict[int, set[int]], depth: int = 2) -> dict[int, int]:
    """Graph distance from the treated set (0 = treated), up to `depth`."""
    ring = {d: 0 for d in treated}
    frontier = set(treated)
    for k in range(1, depth + 1):
        nxt = {n for d in frontier for n in adjacency.get(d, ())} - set(ring)
        ring.update({d: k for d in nxt})
        frontier = nxt
    return ring


def window_change(log_level: pd.DataFrame, q0: pd.Timestamp, pre: int = 8, post: int = 4
                  ) -> pd.Series:
    """Per district: mean log level over quarters 0..post-1 minus mean over -pre..-1."""
    idx = log_level.index
    if q0 not in idx:
        return pd.Series(dtype=float)
    i = idx.get_loc(q0)
    before = log_level.iloc[max(i - pre, 0):i].mean()
    after = log_level.iloc[i:i + post].mean()
    return after - before


def ring_did(change: pd.Series, ring_of: dict[int, int], excluded: set[int],
             n_boot: int = 999, seed: int = 0) -> pd.DataFrame:
    """Ring k minus controls, with a percentile bootstrap over districts."""
    rng = np.random.default_rng(seed)
    ch = change.dropna()
    ring = pd.Series(ring_of).reindex(ch.index)
    control = ch[ring.isna() & ~ch.index.isin(list(excluded))]
    out = []
    for k in sorted(set(ring.dropna().astype(int))):
        grp = ch[ring == k]
        if len(grp) == 0 or len(control) < 2:
            continue
        est = grp.mean() - control.mean()
        boots = [rng.choice(grp.to_numpy(), len(grp)).mean()
                 - rng.choice(control.to_numpy(), len(control)).mean() for _ in range(n_boot)]
        lo, hi = np.percentile(boots, [2.5, 97.5])
        out.append({"ring": k, "n": len(grp), "n_control": len(control), "estimate": est,
                    "lower": lo, "upper": hi})
    return pd.DataFrame(out)


def run(panel: pd.DataFrame, events: pd.DataFrame, ed: pd.DataFrame, edges: pd.DataFrame,
        measure: str = "credit") -> pd.DataFrame:
    from cri.stress.scenarios import adjacency_from_edges

    p = panel[(panel.measure == measure) & (panel.bank_group == "all") & (panel.sector == "all")]
    lvl = np.log(p.pivot_table(index="quarter_end", columns="district_id", values="amount_cr")
                 .where(lambda x: x > 0)).sort_index()
    lvl.index = pd.DatetimeIndex(lvl.index)
    adj = adjacency_from_edges(edges)
    rows = []
    for ev in events.itertuples():
        e = ed[ed.event_id == ev.event_id]
        treated = set(e.district_id[e.treated])
        if not treated:
            continue
        ring_of = rings(treated, adj)
        # partly affected districts outside the rings stay out of the controls
        excluded = set(e.district_id[e.excluded]) - set(ring_of)
        ch = window_change(lvl, pd.Timestamp(ev.impact_quarter))
        res = ring_did(ch, ring_of, excluded)
        if len(res):
            rows.append(res.assign(event_id=ev.event_id))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--measure", default="credit", choices=["credit", "deposits"])
    a = p.parse_args(argv)
    runlog.setup_logging()
    proc = config.path("processed")
    need = ["panel_credit_deposit.parquet", "events.parquet", "event_district.parquet",
            "district_edges.parquet"]
    missing = [n for n in need if not (proc / n).exists()]
    if missing:
        print("not run; missing in data/processed: " + ", ".join(missing))
        return
    res = run(*(pd.read_parquet(proc / n) for n in need), measure=a.measure)
    out = config.path("interim") / f"spillover_rings_{a.measure}.csv"
    res.to_csv(out, index=False)
    print(res.round(4).to_string(index=False))
    print("graph test (H2 against H1 on ring-1 districts): python -m cri.ml.graph.run --ring 1")


if __name__ == "__main__":
    main()
