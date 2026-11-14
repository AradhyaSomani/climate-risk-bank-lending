# District graph model against simpler baselines (Phase 2B-D)

Run on 2026-11-14, after the pre-registration was signed and tagged (`prereg-v1`), with
`python -m cri.ml.graph.run` (credit), `--measure deposits` and `--shuffle-target`. Raw tables:
`data/interim/graph_loeo_credit_ring0.csv`, `graph_loeo_deposits_ring0.csv` and
`graph_leakage_credit.csv`; runs are in MLflow (experiment `graph`). Method and models are in
`docs/model_cards/graph.md`.

**Question.** After a disaster, does knowing what happened in neighbouring districts help
forecast a district's quarterly credit or deposit growth, beyond a simple spatial lag?

**Answer on this data: no.** The graph model (H2) is the worst of the three for every event
and for both measures, and worse than predicting the training mean. The spatial lag (H1) does
not beat the model without any graph (H0) either. The gate (H2 below H1) fails.

## Setup

- Target: quarterly change in log credit or deposits, bank group and sector "all", 640 Census
  2011 districts. Quarters the panel lacks (from 2023 the RBI publishes March only) and series
  breaks are missing, so the two 2023 cyclones (Biparjoy, Michaung) have no test quarters.
- Leave one event out: for each of the 11 remaining events, every quarter of its window
  (impact quarter and the three after) is removed from training for all districts; the models
  are scored on that event's treated districts in that window.
- `naive_train_mean`: RMSE of predicting the training mean, the no-skill reference.

## Credit

| event_id | n_test | naive_train_mean | h0_no_graph | h1_spatial_lag | h2_graph_conv |
| --- | --- | --- | --- | --- | --- |
| FL-2008-KOSI | 72 | 0.0779 | 0.0742 | 0.0741 | 0.0829 |
| CY-2013-PHAILIN | 64 | 0.0372 | 0.0298 | 0.0306 | 0.0440 |
| CY-2014-HUDHUD | 16 | 0.0382 | 0.0225 | 0.0230 | 0.0299 |
| FL-2015-CHENNAI | 9 | 0.0324 | 0.0189 | 0.0234 | 0.0508 |
| FL-2018-KERALA | 12 | 0.0299 | 0.0245 | 0.0201 | 0.0462 |
| CY-2018-GAJA | 36 | 0.0162 | 0.0237 | 0.0254 | 0.0259 |
| CY-2019-FANI | 88 | 0.0269 | 0.0354 | 0.0381 | 0.0399 |
| CY-2020-AMPHAN | 48 | 0.0315 | 0.0290 | 0.0301 | 0.0390 |
| CY-2020-NIVAR | 28 | 0.0248 | 0.0245 | 0.0233 | 0.0382 |
| CY-2021-TAUKTAE | 24 | 0.0487 | 0.0273 | 0.0293 | 0.0447 |
| CY-2021-YAAS | 32 | 0.0406 | 0.0252 | 0.0261 | 0.0499 |
| **mean** | 429 | 0.0367 | **0.0305** | 0.0312 | 0.0447 |

Gate (H2 below H1): **failed**.

## Deposits

| event_id | n_test | naive_train_mean | h0_no_graph | h1_spatial_lag | h2_graph_conv |
| --- | --- | --- | --- | --- | --- |
| FL-2008-KOSI | 72 | 0.0727 | 0.0570 | 0.0568 | 0.1149 |
| CY-2013-PHAILIN | 64 | 0.0541 | 0.0466 | 0.0482 | 0.0656 |
| CY-2014-HUDHUD | 16 | 0.0338 | 0.0241 | 0.0229 | 0.0351 |
| FL-2015-CHENNAI | 9 | 0.0270 | 0.0144 | 0.0162 | 0.0396 |
| FL-2018-KERALA | 12 | 0.0153 | 0.0384 | 0.0349 | 0.0898 |
| CY-2018-GAJA | 36 | 0.0233 | 0.0138 | 0.0159 | 0.0290 |
| CY-2019-FANI | 88 | 0.0278 | 0.0261 | 0.0261 | 0.0312 |
| CY-2020-AMPHAN | 48 | 0.0181 | 0.0230 | 0.0225 | 0.0327 |
| CY-2020-NIVAR | 28 | 0.0291 | 0.0356 | 0.0365 | 0.0425 |
| CY-2021-TAUKTAE | 24 | 0.0207 | 0.0295 | 0.0309 | 0.0727 |
| CY-2021-YAAS | 32 | 0.0290 | 0.0339 | 0.0349 | 0.0382 |
| **mean** | 429 | 0.0319 | **0.0311** | 0.0314 | 0.0537 |

Gate (H2 below H1): **failed**.

## Leakage check (credit, shuffled target)

| model | rmse | naive_rmse | ratio | collapsed |
| --- | --- | --- | --- | --- |
| h0_no_graph | 0.0626 | 0.0615 | 1.017 | yes |
| h1_spatial_lag | 0.0633 | 0.0615 | 1.029 | yes |
| h2_graph_conv | 0.0737 | 0.0615 | 1.198 | yes |

On a shuffled target every model loses its skill, so nothing in the inputs leaks the target.

## Reading

- **Relative to no skill.** For credit, H0 cuts the error of the training mean by 17% and H1
  by 15%. For deposits the gain is only 2.5% (H0) and 1.6% (H1): deposit growth after these
  events is close to unpredictable from a district's own past and shocks.
- **Spatial lag.** H1 beats H0 on 3 of 11 events for credit (Kerala clearly; Kosi and Nivar
  narrowly) and 4 of 11 for deposits (Kosi, Hudhud, Kerala, Amphan), and loses on the mean for
  both. Neighbours' last-quarter growth and shocks add nothing on average.
- **Graph model.** H2 is above H1 on all 22 event-measure pairs and above the training mean
  on average (1.22 times for credit, 1.68 for deposits). With a few hundred treated test rows
  and one network fitted per event, it overfits; the same pattern showed on the simulated grid
  in the model card. A smaller network or early stopping might narrow the gap, but tuning it
  now on these held-out events would be fitting to the test set, so it is not done.
- **Kerala** is the one event where the neighbour terms help clearly for both measures
  (credit H1 0.0201 against H0 0.0245). It is one event of 3 treated districts, 12 test rows.

## Consequence

H2 is recorded as a negative result (Phase 2B gate). The graph model is not used in any
estimate. For the spillover question (Phase 3F), the primary tool stays the ring
difference-in-differences against far controls (`python -m cri.events.spillover`), with the
`--ring 1` model comparison reported next to it.
