# District graph model (Phase 2B-D)

## Purpose
Test whether neighbouring districts carry information about a district's lending after a
disaster beyond a simple spatial lag. Feeds the spillover check in Phase 3F.

## Data
- Graph: `data/processed/district_graph.npz` and `district_edges.parquet` from
  `python -m cri.ml.graph.build`. Queen contiguity on Census 2011 polygons with a 200 m snap
  for border gaps; edge weight = shared boundary length (km). 640 districts, 1,745 edges,
  median degree 5; Lakshadweep and Nicobar have no neighbours. Spot checks: Ernakulam ->
  Alappuzha, Idukki, Kottayam, Thrissur; Puri -> Cuttack, Ganjam, Jagatsinghapur, Khordha.
- Target: quarterly change in log credit (bank group and sector "all") from B's panel
  (contract C2), with series breaks set to missing.
- Shocks: treated flags at the impact quarter and the three after it, from the event
  catalogue (contract C4).

## Baseline and gate
- H0: ridge on own four lags, own shock terms and quarter dummies.
- H1: H0 plus neighbour averages of last quarter's growth and of the shock terms.
- H2: two-layer GraphSAGE-mean network (plain PyTorch, dense row-standardised adjacency).
- Metric: RMSE on each held-out event's treated districts in its window, leave-one-event-out,
  with every quarter of the held-out window removed from training. Gate: H2 below H1.
- Result: **not run**. Needs `panel_credit_deposit.parquet` from B. The code is tested on a
  simulated grid where shocks spill over (H1 beats H0 there, as it should).

## Spillover use (Phase 3F)
`python -m cri.ml.graph.run --ring 1` scores the three models on the neighbours of treated
districts instead of the treated ones, next to the ring difference-in-differences in
`python -m cri.events.spillover` (ring 1 and ring 2 against far controls, bootstrap interval).

## Model
Ridge with alpha 1 for H0 and H1; H2 with 16 hidden units, Adam (lr 0.01, weight decay
1e-4), 300 full-batch epochs.

## Compute
CPU; seconds per event on 640 districts.

## Intended use and limits
With only a handful of large events, H2 will be hard to separate from H1. The ablation table
is the contribution, whichever way it comes out.

## Failure cases
Not yet observed on real data.
