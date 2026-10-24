PY ?= python
DATABASE_URL ?= postgresql://postgres@localhost:5432/cri

.PHONY: install lint test contracts ci data hazard events stress all dvc-remote db api api-sample \
	checksums

install:
	$(PY) -m pip install -e ".[geo,api,dev]"

lint:
	$(PY) -m ruff check src tests scripts

test:
	$(PY) -m pytest -m "not gee and not db"

contracts:
	$(PY) -m cri.contracts --samples

ci: lint contracts test

# Pipeline stages; each step is logged to data/processed/run_log.csv
data:
	$(PY) -m cri.pipeline data

hazard: data
	$(PY) -m cri.pipeline hazard

events: hazard
	$(PY) -m cri.pipeline events

stress: events
	$(PY) -m cri.pipeline stress

all: stress

# One shared DVC remote for both people, e.g. make dvc-remote URL=gdrive://<folder-id>
dvc-remote:
	dvc remote add -d -f storage $(URL)

# Read-only API (Phase 5A): on data/processed, or on the contract samples (no data needed)
api:
	uvicorn cri.api.app:app --reload

api-sample:
	CRI_API_SOURCE=sample uvicorn cri.api.app:app --reload

# Raw downloads against docs/raw_checksums.sha256 (docs/data_access.md)
checksums:
	$(PY) scripts/raw_checksums.py --check

db:
	DATABASE_URL=$(DATABASE_URL) $(PY) scripts/load_db.py
