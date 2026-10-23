PY ?= python
DATABASE_URL ?= postgresql://postgres@localhost:5432/cri

.PHONY: install lint test contracts ci data hazard events stress all dvc-remote db

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

db:
	DATABASE_URL=$(DATABASE_URL) $(PY) scripts/load_db.py
