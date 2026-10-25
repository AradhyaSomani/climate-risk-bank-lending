# Climate Risk in Indian Bank Lending

Measures how much Indian bank lending sits in districts exposed to floods and cyclones, estimates what happened to district credit and deposits after past disasters, and builds a stress test with honest intervals from those measured effects.

Team: Aradhya Somani (data and ML), Devna Roopesh (econometrics and product).

Status: Phase 0, feasibility.

**This is academic research.** No bank is being assessed as unsound. The RBI district data show outstanding credit and deposits by branch location, not defaults, so nothing here is a loss estimate, a solvency call or investment advice.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install-pinned   # the pinned versions in requirements/lock.txt, then the package itself
make test             # unit tests (Earth Engine and database tests are skipped)
make lint
```

`make install-pinned-ml` adds the ML packages (`requirements/lock-ml.txt`). `make install`
installs the latest versions instead (`pip install -e ".[geo,api,dev,report]"`); optional
extras are `.[gee]` for Earth Engine pulls, `.[ml]` for the models in `src/cri/ml` and `.[db]`
for the PostGIS loader. After changing dependencies in `pyproject.toml`, run `make lock`
(needs [uv](https://docs.astral.sh/uv/)) and commit both lock files.

## Pipeline

```bash
make data      # B: district master, crosswalk, RBI panel, controls
make hazard    # A: flood extent, cyclone footprints, hazard baseline, scores
make events    # event catalogue and treatment flags, then the event study
make stress    # scenarios and the stress test
make all       # all four in order
make rebuild   # pinned environment, dvc pull if a remote is set, then make all
```

Settings live in `configs/*.yaml` (`paths`, `project`, `hazard`, ...). Every step appends a row
to `data/processed/run_log.csv` with the git commit, data version and a hash of the configs,
so any table can be traced to the code that made it. `python -m cri.pipeline <stage> --list`
shows the steps registered so far. Data is versioned with DVC in a shared Google Drive
folder; `data/README.md` has the one-time setup (`make dvc-remote`) and the daily commands.

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
