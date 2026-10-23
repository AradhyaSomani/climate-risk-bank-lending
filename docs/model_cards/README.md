# Model cards (Phase 2B)

One card per model in `src/cri/ml/`, written from `TEMPLATE.md`. The rule of the ML track:
a model is kept only if it beats its baseline on the stated metric; otherwise it is listed
here as a negative result with its numbers.

| Component | Card | Baseline | Gate metric | Status |
| --- | --- | --- | --- | --- |
| U-Net flood mapper | `flood_cnn.md` | Otsu on VV and VH (change detection once a pre-event scene is exported) | IoU of water on held-out events | not run |
| Flood susceptibility | `susceptibility.md` | Flood-event count | Spatial block CV AUC | not run |
| District graph model | `graph.md` | No graph (H0), spatial lag (H1) | Leave-one-event-out RMSE | not run |
| State-space counterfactual | `statespace.md` | Parallel-trend DiD, ARIMA | Placebo-event error | not run |
| Causal forest / double ML | `causal_ml.md` | Subgroup regressions | Stability across left-out events | not run |
| LLM table extractor | `extract.md` | Manual extraction | Cell accuracy after the verifier (98%) | not run |

## Tracking

Every run goes through `cri.ml.tracking.start_run`, which logs parameters, metrics, the data
version, the git commit, the hardware and the run time to a local MLflow store in `mlruns/`
(`mlflow ui --backend-store-uri mlruns` to browse). `record_gate` writes the gate result to
`data/processed/model_runs.parquet`, which loads into the warehouse table `model_run`.
Only models that passed are copied to `data/models/`.

## Compute plan

All models are small. The U-Net runs on a free GPU notebook (Colab or Kaggle) or, slowly, on
CPU; everything else runs on a laptop CPU. Each card records the hardware and run time.
