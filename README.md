# Climate Risk in Indian Bank Lending

Measures how much Indian bank lending sits in districts exposed to floods and cyclones, estimates what happened to district credit and deposits after past disasters, and builds a stress test with honest intervals from those measured effects.

Team: Aradhya Somani (Person A, data and ML), Devna Roopesh (Person B, econometrics and product). See `CONTRIBUTORS.md`.

**This is academic research.** No bank is being assessed as unsound. The RBI district data show outstanding credit and deposits by branch location, not defaults, so nothing here is a loss estimate, a solvency call or investment advice.

## Where things stand (25 October 2026)

| Phase | Done | Next |
| --- | --- | --- |
| 0. Feasibility | RBI audit: district deposits and credit every quarter from March 2004 to December 2022, with a gap from September 2016 to March 2017 (`docs/00_rbi_audit.md`). Location-basis test on March 2007 (`docs/00_location_basis.md`). Pre-registration drafted (`docs/00_hypotheses.md`). | Agree the two open items in the pre-registration, sign it and tag `prereg-v1`. Power check (0E). State banker committee comparison (0B2). |
| 1. Data foundation | Configs and run log, flood extents (Global Flood Database), cyclone footprints (IMD), EM-DAT records linked to the events, hazard baseline, PostGIS loader, data tests and cards | District crosswalk (1B) and the RBI credit and deposit panel (1C). The Kerala 2018 flood extent needs Sentinel-1 through Earth Engine. |
| 2. Hazard and exposure | District hazard indicators, composite scores and their validation | Lending exposure (2D to 2F), once the panel exists |
| 2B. ML track | U-Net flood mapper and flood susceptibility model passed their gates; shuffled-label leakage checks (`docs/model_cards/`) | District graph model, once the panel exists |
| 3. Event study | Event catalogue and treatment flags | Estimators, after the panel and the signed pre-registration |
| 4. Stress test | Scenarios and the stochastic event generator | The stress test itself, from the measured effects |
| 5. Product | Read-only API, pinned environment, `make rebuild` | Dashboard, paper, release |

## Setup

Python 3.10 or later (CI runs 3.10 and 3.12).

```bash
git clone https://github.com/AradhyaSomani/climate-risk-bank-lending.git
cd climate-risk-bank-lending
python3 -m venv .venv
source .venv/bin/activate
make install-pinned
make test
```

`make install-pinned` installs the pinned versions in `requirements/lock.txt`, then the
package itself. `make test` runs the unit tests; Earth Engine and database tests are skipped.
`make install-pinned-ml` adds the ML packages (`requirements/lock-ml.txt`). `make install`
installs the latest versions instead (`pip install -e ".[geo,api,dev,report]"`); optional
extras are `.[gee]` for Earth Engine pulls, `.[ml]` for the models in `src/cri/ml` and `.[db]`
for the PostGIS loader. After changing dependencies in `pyproject.toml`, run `make lock`
(needs [uv](https://docs.astral.sh/uv/)) and commit both lock files.

## Data

Data is not in Git. It is versioned with DVC (`data/raw.dvc`, `data/processed.dvc`,
`data/models.dvc`), and the files live in a shared Google Drive folder, `cri-dvc-store`,
synced by Google Drive for desktop. Once the folder is shared with you and synced:

```bash
make dvc-remote URL="$(echo ~/Library/CloudStorage/GoogleDrive-*/My\ Drive/cri-dvc-store)"
dvc remote list
dvc pull
```

The `make dvc-remote` line finds the folder on a Mac; elsewhere, put the path of the synced
folder after `URL=`. `data/README.md` has the full setup, the daily commands and the data
versions. Each raw source has a data card in `docs/data_cards/` with its source, licence
and download date, and `docs/raw_checksums.sha256` holds a checksum of every raw file.

Two sources are never shared, through Git or DVC:

- **EM-DAT**: its terms forbid passing the export on. Each of us downloads our own from
  public.emdat.be and saves it in `data/raw/emdat/`.
- **Sen1Floods11** (training chips for the U-Net): no licence allows sharing it.
  `python -m cri.ingest.sen1floods11` downloads it.

RBI files have no open licence either: the raw files are never published, and every figure
made from them carries a source line.

## Pipeline

| Command | What it runs |
| --- | --- |
| `make data` | District master, crosswalk, RBI panel, controls (Person B) |
| `make hazard` | Flood extent, cyclone footprints, hazard baseline, scores (Person A) |
| `make events` | Event catalogue and treatment flags, then the event study |
| `make stress` | Scenarios and the stress test |
| `make all` | All four in order |
| `make rebuild` | The pinned environment, `dvc pull` if a remote is set, then `make all` |

Settings live in `configs/*.yaml` (`paths`, `project`, `hazard`, `events`, ...). Every step
appends a row to `data/processed/run_log.csv` with the git commit, data version and a hash
of the configs, so any table can be traced to the code that made it.
`python -m cri.pipeline hazard --list` shows the steps registered for a stage.

## Pre-registration

The event study is pre-registered in `docs/00_hypotheses.md`. Until both of us have signed
section 9 and the commit is tagged `prereg-v1`, nobody looks at district credit or deposits
around the events: no plots, no before-and-after comparisons. `scripts/rbi_first_look.py`
prints coverage only; its `--plots` option stays unused until the tag exists. After
signing, every change goes through `docs/decision_log.md` with its date, its reason and
whether any outcome had been seen.

## Key documents

| File | What is in it |
| --- | --- |
| `docs/00_rbi_audit.md` | RBI coverage, units, banks, series breaks and the verdict for the Phase 0 gate |
| `docs/00_location_basis.md` | Credit by place of sanction against place of utilisation, and the proposed rule for metro districts |
| `docs/00_hypotheses.md` | The pre-registration (draft until signed) |
| `docs/00_hazard_data_audit.md` | The hazard data audit |
| `docs/decision_log.md` | Every decision, with its date and reason |
| `docs/contracts/` | Schemas of the shared tables (C1 to C5); `python -m cri.contracts --processed` checks them |
| `docs/data_cards/`, `docs/model_cards/` | One card per data source and per model |
| `docs/eval_reports/` | Hazard coverage, score stability, cyclone landfall and event generator checks |
| `docs/data_access.md`, `docs/api.md` | How to get each dataset; the read-only API |

## Layout

```text
configs/       YAML: data paths, hazard and event rules, estimator settings, scenarios
data/          raw, interim, processed and models (DVC), events (Git); see data/README.md
docs/          audits, pre-registration, contracts, data and model cards, eval reports, decision log
src/cri/       ingest, geo, hazard, exposure, events, stress, ml, api, db
scripts/       one-off checks: RBI first look, location basis, checksums, contract validation
requirements/  pinned lock files
tests/
app/           dashboard (not started)
```

## Working on this repo

- Every change goes through a pull request, from a branch named `a/<topic>` (Aradhya) or
  `b/<topic>` (Devna) and cut from an up-to-date `main`. Nobody commits to `main` directly.
- Before every push, run `make ci` (ruff, the contract samples and the tests) and
  `python -m cri.contracts --processed`. CI must be green on Python 3.10 and 3.12.
- A pull request has a clear title, a summary, the changes per task-list section, and how
  it was tested.
- Only Aradhya merges to `main` (rebase or squash).
- Branches are kept after their merge, never deleted. A merged branch is not reused: new
  work starts a new branch from `main`.
- No data files or secrets in Git. Data moves through DVC; EM-DAT is never shared.
