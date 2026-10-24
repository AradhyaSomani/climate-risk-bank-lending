"""Stage runner behind `make data`, `make hazard`, `make events` and `make stress`.

Each stage is an ordered list of steps, given as "module:function". A step takes no
arguments, reads its settings from configs/, and returns the list of files it wrote. Every
step is logged to the run table (cri.runlog). Steps owned by Person B are registered by B.

    python -m cri.pipeline hazard            # run every step of a stage
    python -m cri.pipeline hazard --list     # show the steps
"""

from __future__ import annotations

import argparse
import importlib
import logging

from cri import runlog

log = logging.getLogger(__name__)

STAGES: dict[str, list[str]] = {
    "data": [],
    "hazard": [
        "cri.hazard.flood_extent:build_gfd",
        "cri.hazard.cyclone_footprint:build",
        "cri.ingest.emdat:build_default",
        "cri.hazard.baseline:build",
        "cri.hazard.indicators:build",
        "cri.hazard.score:build",
        "cri.hazard.validation:run",
    ],
    "events": ["cri.ml.graph.build:build", "cri.events.catalogue:build"],
    "stress": ["cri.stress.scenarios:build", "cri.stress.event_generator:build"],
}

STAGE_CONFIGS: dict[str, list[str]] = {
    "data": ["project", "paths"],
    "hazard": ["project", "paths", "hazard"],
    "events": ["project", "paths", "events", "ml/graph"],
    "stress": ["project", "paths", "scenarios"],
}


def resolve(step: str):
    module, func = step.split(":")
    return getattr(importlib.import_module(module), func)


def run_stage(stage: str) -> None:
    steps = STAGES[stage]
    if not steps:
        log.warning("stage %s has no steps registered yet", stage)
    for step in steps:
        log.info("%s: %s", stage, step)
        with runlog.run(f"{stage}:{step}", STAGE_CONFIGS[stage]) as outputs:
            outputs.extend(str(p) for p in (resolve(step)() or []))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("stage", choices=sorted(STAGES))
    p.add_argument("--list", action="store_true")
    a = p.parse_args(argv)
    runlog.setup_logging()
    if a.list:
        print("\n".join(STAGES[a.stage]) or "(no steps yet)")
        return
    run_stage(a.stage)


if __name__ == "__main__":
    main()
