PY ?= python
DATABASE_URL ?= postgresql://postgres@localhost:5432/cri

.PHONY: install install-pinned install-pinned-ml lock lint test contracts ci data hazard events \
	stress all rebuild dvc-remote dvc-track db api api-sample checksums

install:
	$(PY) -m pip install -e ".[geo,api,dev,report]"

# The pinned environment (every package at one version, Python 3.10 to 3.14, macOS 14+,
# Linux, Windows). `make rebuild` and CI use it. After changing pyproject.toml, run
# `make lock` (needs uv) and commit the two lock files.
install-pinned:
	$(PY) -m pip install -r requirements/lock.txt
	$(PY) -m pip install --no-deps -e .

install-pinned-ml:
	$(PY) -m pip install -r requirements/lock-ml.txt
	$(PY) -m pip install --no-deps -e .

# lock-ml.txt is solved first and lock.txt inside it, so a package in both has one version
LOCK_FLAGS = --universal --python-version 3.10 --no-header --annotation-style line \
	-c requirements/constraints.txt --extra geo --extra api --extra report --extra dev --extra db
lock:
	MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile pyproject.toml $(LOCK_FLAGS) --extra ml \
		-o requirements/lock-ml.txt
	MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile pyproject.toml $(LOCK_FLAGS) \
		-c requirements/lock-ml.txt -o requirements/lock.txt

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

# One command from raw data to the final tables on a clean checkout: the pinned environment,
# the raw data from the DVC remote when one is set (otherwise what is already in data/raw,
# see docs/data_access.md), then every stage
rebuild: install-pinned
	@if dvc remote list 2>/dev/null | grep -q .; then dvc pull; \
	else echo "No DVC remote set; using the files already in data/raw"; fi
	$(MAKE) all

# DVC: one shared remote, a Google Drive folder synced by Google Drive for desktop. Its path
# differs per machine, so it goes in .dvc/config.local, which is not committed:
#   make dvc-remote URL="$$(echo ~/Library/CloudStorage/GoogleDrive-*/My\ Drive/cri-dvc-store)"
dvc-remote:
	dvc remote add --local -d -f storage "$(URL)"

# Folders under DVC: data/raw (without EM-DAT and Sen1Floods11, see .dvcignore), the
# processed tables and the models that passed their gate. Run it after any rebuild that
# changes them, then `dvc push` and commit the .dvc files.
dvc-track:
	dvc add $(wildcard data/raw data/processed data/models)

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
