# <Model name>

Copy this file to `docs/model_cards/<component>.md` and fill every section. Write
"not measured" rather than leaving a section out.

## Purpose
The problem it solves in this project, and the decision or table that uses its output.

## Data
- Training data, with its data card and data version.
- Split: how train, validation and test are separated (by event, region or spatial block,
  never at random), and what is held out.
- Known label problems.

## Baseline and gate
- Baseline(s) and the metric, as fixed in `configs/ml/<component>.yaml` before training.
- Result table: baseline score, model score, per held-out unit and averaged.
- Gate outcome: passed or failed. A failed model is a negative result and stays out of the
  pipeline; say so here with the numbers.

## Model
Architecture, inputs, loss, main hyperparameters, and the ablations that were run.

## Compute
Hardware, run time and the MLflow run id(s) (`mlruns/`, experiment `<component>`).

## Intended use and limits
Where the output can be used, and where it must not be (regions, periods, land cover).

## Failure cases
Concrete examples where it is wrong, with figures if possible.
