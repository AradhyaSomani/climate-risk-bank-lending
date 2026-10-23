PY ?= python

.PHONY: install lint test contracts ci

install:
	$(PY) -m pip install -e ".[geo,api,dev]"

lint:
	$(PY) -m ruff check src tests scripts

test:
	$(PY) -m pytest -m "not gee and not db"

contracts:
	$(PY) -m cri.contracts --samples

ci: lint contracts test
