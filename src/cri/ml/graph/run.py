"""Run the Phase 2B-D comparison (H0, H1, H2) and record the gate.

Needs B's panel (`panel_credit_deposit.parquet`, contract C2) and the event catalogue
(`events.parquet`, `event_district.parquet`, contract C4). Until both exist it says what is
missing and stops.

    python -m cri.ml.graph.run
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from cri import config
from cri.ml import tracking
from cri.ml.graph import models
from cri.ml.graph.build import load_graph, row_normalised

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--measure", default="credit", choices=["credit", "deposits"])
    a = p.parse_args(argv)
    runlog.setup_logging()
    proc = config.path("processed")
    need = ["panel_credit_deposit.parquet", "events.parquet", "event_district.parquet",
            "district_graph.npz"]
    missing = [n for n in need if not (proc / n).exists()]
    if missing:
        print("not run; missing in data/processed: " + ", ".join(missing))
        return
    cfg = config.load("ml/graph")
    graph = load_graph()
    w = row_normalised(graph, weighted=cfg["graph"].get("weights") != "binary")
    y = models.credit_growth(pd.read_parquet(proc / need[0]), a.measure)
    y = y.reindex(columns=graph["ids"])
    events = pd.read_parquet(proc / "events.parquet")
    ed = pd.read_parquet(proc / "event_district.parquet")
    s = models.shock_matrix(events, ed, y.index, y.columns)
    d = models.design(y, s, w)
    with tracking.start_run("graph", {"measure": a.measure, **cfg["graph"]},
                            run_name=f"loeo_{a.measure}") as run:
        res = models.leave_one_event_out(d, events, ed, w)
        mean = res[res.event_id == "mean"].iloc[0]
        run.log_metrics({k: mean[k] for k in ("h0_no_graph", "h1_spatial_lag", "h2_graph_conv")})
        passed = tracking.record_gate(run, "h1_spatial_lag", mean.h1_spatial_lag,
                                      mean.h2_graph_conv, metric=cfg["gate"]["metric"],
                                      higher_is_better=False)
    out = config.path("interim") / f"graph_loeo_{a.measure}.csv"
    res.to_csv(out, index=False)
    print(res.round(4).to_string(index=False))
    print("gate (H2 beats H1):", "passed" if passed else "failed")


if __name__ == "__main__":
    main()
