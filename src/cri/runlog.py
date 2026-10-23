"""Run tracking: every pipeline stage appends one row to the run table.

The row records the git commit, whether the tree was dirty, the data version from
configs/project.yaml, a hash of the configs used, and the outputs written, so any table in a
report can be traced back to the code and settings that produced it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cri import config

FIELDS = [
    "run_id", "stage", "started_at", "seconds", "git_commit", "git_dirty", "data_version",
    "config_hash", "configs", "outputs", "status",
]


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True
    )


def git_state(root: Path = config.REPO_ROOT) -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=root, capture_output=True, text=True, check=True,
            ).stdout.strip()
        )
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def config_hash(names: list[str]) -> str:
    blob = json.dumps({n: config.load(n) for n in sorted(names)}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


@contextmanager
def run(stage: str, configs: list[str], table: Path | None = None):
    """Context manager around a stage. Yields a list; append output paths to it."""
    table = table or config.path("runs")
    outputs: list[str] = []
    commit, dirty = git_state()
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    status = "ok"
    try:
        yield outputs
    except Exception:
        status = "failed"
        raise
    finally:
        row = {
            "run_id": f"{stage}-{started.strftime('%Y%m%dT%H%M%S')}",
            "stage": stage,
            "started_at": started.isoformat(timespec="seconds"),
            "seconds": round(time.monotonic() - t0, 2),
            "git_commit": commit,
            "git_dirty": dirty,
            "data_version": config.load("project").get("data_version", "dev"),
            "config_hash": config_hash(configs),
            "configs": ";".join(configs),
            "outputs": ";".join(str(o) for o in outputs),
            "status": status,
        }
        table.parent.mkdir(parents=True, exist_ok=True)
        new = not table.exists()
        with table.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
