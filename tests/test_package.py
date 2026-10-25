import importlib

import pytest

SUBPACKAGES = ["ingest", "geo", "hazard", "exposure", "events", "stress", "api", "ml"]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name):
    importlib.import_module(f"cri.{name}")
