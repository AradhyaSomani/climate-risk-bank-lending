"""District adjacency graph from shared boundaries (Phase 2B-D).

Two districts are neighbours when their polygons touch (queen contiguity: a shared edge or
corner). Census 2011 polygons have small gaps and overlaps at shared borders, so polygons
closer than `snap_m` count as touching. The edge weight is the shared boundary length in km,
measured as the area of the overlap of the two polygons buffered by snap_m / 2, divided by
snap_m; corner-only contacts get a small weight.

Outputs:
- data/processed/district_edges.parquet: one row per pair (a < b) with `weight` (km) and
  `corner_only`; loads into the warehouse table `district_edge`.
- data/processed/district_graph.npz: `ids`, `edge_index` (2 x E, both directions) and
  `weight`, ready for the graph models.

    python -m cri.ml.graph.build
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

from cri import config

log = logging.getLogger(__name__)

EDGES_NAME = "district_edges.parquet"
GRAPH_NAME = "district_graph.npz"


def edges(districts_metric, snap_m: float = 200.0) -> pd.DataFrame:
    """Undirected edges (a < b) with shared boundary length in km."""
    g = districts_metric.reset_index(drop=True)
    half = g.geometry.buffer(snap_m / 2).to_numpy()
    ids = g.district_id.to_numpy()
    left, right = g.sindex.query(half, predicate="intersects")
    keep = left < right
    left, right = left[keep], right[keep]
    # the same buffered geometries on both sides: overlap strip is about snap_m wide
    overlap = shapely.area(shapely.intersection(half[left], half[right]))
    km = overlap / snap_m / 1000.0
    out = pd.DataFrame({"a": ids[left], "b": ids[right], "weight": km})
    swap = out.a > out.b
    out.loc[swap, ["a", "b"]] = out.loc[swap, ["b", "a"]].to_numpy()
    out["corner_only"] = out.weight < 2 * snap_m / 1000.0
    return out.sort_values(["a", "b"]).reset_index(drop=True)


def to_graph(e: pd.DataFrame, ids) -> dict[str, np.ndarray]:
    ids = np.asarray(sorted(ids))
    pos = {d: i for i, d in enumerate(ids)}
    a = e.a.map(pos).to_numpy()
    b = e.b.map(pos).to_numpy()
    edge_index = np.stack([np.r_[a, b], np.r_[b, a]]).astype("int64")
    weight = np.r_[e.weight.to_numpy(), e.weight.to_numpy()].astype("float32")
    return {"ids": ids, "edge_index": edge_index, "weight": weight}


def row_normalised(graph: dict[str, np.ndarray], weighted: bool = True) -> np.ndarray:
    """Dense row-standardised W (n x n); isolated districts get a zero row."""
    n = len(graph["ids"])
    w = np.zeros((n, n), dtype="float64")
    src, dst = graph["edge_index"]
    w[src, dst] = graph["weight"] if weighted else 1.0
    s = w.sum(axis=1, keepdims=True)
    return np.divide(w, s, out=np.zeros_like(w), where=s > 0)


def load_graph(path: Path | None = None) -> dict[str, np.ndarray]:
    path = path or config.path("processed") / GRAPH_NAME
    f = np.load(path)
    return {k: f[k] for k in ("ids", "edge_index", "weight")}


def build() -> list[Path]:
    from cri.geo.districts import load_districts

    cfg = config.load("ml/graph")["graph"]
    d = load_districts().to_crs(config.load("project")["crs"]["metric"])
    e = edges(d, cfg["snap_m"])
    if cfg.get("weights") == "binary":
        e["weight"] = 1.0
    processed = config.path("processed")
    processed.mkdir(parents=True, exist_ok=True)
    ep = processed / EDGES_NAME
    e.to_parquet(ep, index=False)
    g = to_graph(e, d.district_id)
    gp = processed / GRAPH_NAME
    np.savez_compressed(gp, **g)
    deg = pd.Series(np.bincount(g["edge_index"][0], minlength=len(g["ids"])), index=g["ids"])
    log.info("wrote %s and %s: %d districts, %d edges, %d isolated, median degree %d",
             ep, gp, len(g["ids"]), len(e), int((deg == 0).sum()), int(deg.median()))
    return [ep, gp]


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("ml:graph_build", ["project", "paths", "ml/graph"]) as outputs:
        outputs += build()


if __name__ == "__main__":
    main()
