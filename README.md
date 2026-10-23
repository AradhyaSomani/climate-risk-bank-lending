# Climate Risk in Indian Bank Lending

Measures how much Indian bank lending sits in districts exposed to floods and cyclones, estimates what happened to district credit and deposits after past disasters, and builds a stress test with honest intervals from those measured effects.

Team: Aradhya Somani (data and ML), Devna Roopesh (econometrics and product).

Status: Phase 0, feasibility.

**This is academic research.** No bank is being assessed as unsound. The RBI district data show outstanding credit and deposits by branch location, not defaults, so nothing here is a loss estimate, a solvency call or investment advice.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install      # pip install -e ".[geo,api,dev]"
make test         # unit tests (Earth Engine and database tests are skipped)
make lint
```

Optional extras: `.[gee]` for Earth Engine pulls, `.[ml]` for the models in `src/cri/ml`, `.[db]` for the PostGIS loader.

## Layout

```text
configs/   YAML: data paths, estimator settings, scenarios
data/      raw, interim, processed (DVC) and events (Git); see data/README.md
docs/      data_cards, model_cards, contracts, eval_reports, decisions, decision_log.md
src/cri/   ingest, geo, hazard, exposure, events, stress, ml, api
app/       dashboard
tests/
```

## Working on this repo
- Never commit to `main`. Work on a branch named `a/<topic>` or `b/<topic>` and open a pull request.
- Every pull request needs one approval from the other person.
- No data files or secrets in Git.
