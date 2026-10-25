# Model cards (Phase 2B)

One card per model in `src/cri/ml/`, written from `TEMPLATE.md`. The rule of the ML track:
a model is kept only if it beats its baseline on the stated metric; otherwise it is listed
here as a negative result with its numbers.

| Component | Card | Baseline | Gate metric | Status | Leakage check (shuffled labels) |
| --- | --- | --- | --- | --- | --- |
| U-Net flood mapper | `flood_cnn.md` | Otsu on VV and VH per chip, fixed VV and VH thresholds fitted on training events | IoU of water on held-out events | **passed** (0.628 vs 0.466); Kerala run waits for the Earth Engine export | seed 7 collapsed (0.072); seed 42 did not (0.261 vs all-water 0.142) but stays below label-free Otsu (0.324); see card |
| Flood susceptibility | `susceptibility.md` | Flood-event count before 2012 | Spatial block CV AUC on later floods | **passed** (0.905 vs 0.880); added as score version `susceptibility` | collapsed (AUC 0.50) |
| District graph model | `graph.md` | No graph (H0), spatial lag (H1) | Leave-one-event-out RMSE | graph built; models wait for the credit panel | collapsed on the simulated grid; real panel waits |
| State-space counterfactual | `statespace.md` | Parallel-trend DiD, ARIMA | Placebo-event error | not run | not run |
| Causal forest / double ML | `causal_ml.md` | Subgroup regressions | Stability across left-out events | not run | not run |
| LLM table extractor | `extract.md` | Manual extraction | Cell accuracy after the verifier (98%) | not run | not run |

## Tracking

Every run goes through `cri.ml.tracking.start_run`, which logs parameters, metrics, the data
version, the git commit, the hardware and the run time to a local MLflow store in `mlruns/`
(`mlflow ui --backend-store-uri mlruns` to browse). `record_gate` writes the gate result to
`data/processed/model_runs.parquet`, which loads into the warehouse table `model_run`.
Only models that passed are copied to `data/models/`.

## Compute plan

All models are small. The U-Net runs on a free GPU notebook (Colab or Kaggle) or, slowly, on
CPU; everything else runs on a laptop CPU. Each card records the hardware and run time.
