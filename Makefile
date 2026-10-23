PY ?= python

.PHONY: install lint test ci

install:
	$(PY) -m pip install -e ".[geo,api,dev]"

lint:
	$(PY) -m ruff check src tests scripts

test:
	$(PY) -m pytest -m "not gee and not db"

ci: lint test
