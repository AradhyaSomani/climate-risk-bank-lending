"""Load YAML configs from configs/ and resolve repo-relative paths."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"


@cache
def load(name: str) -> dict[str, Any]:
    """Load configs/<name>.yaml (name may include a subfolder, e.g. 'ml/flood_cnn')."""
    path = CONFIG_DIR / f"{name}.yaml"
    with path.open() as f:
        return yaml.safe_load(f) or {}


def path(key: str) -> Path:
    """Absolute path for a key in configs/paths.yaml; dotted keys reach nested entries."""
    node: Any = load("paths")
    for part in key.split("."):
        node = node[part]
    return REPO_ROOT / node


def district_geometry_path() -> Path:
    """B's district master if it exists, else the provisional DataMeet shapefile."""
    preferred = path("district_geometry.preferred")
    return preferred if preferred.exists() else path("district_geometry.fallback")
