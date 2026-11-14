"""Guard for steps that look at post-event credit or deposits.

The pre-registration (`docs/00_hypotheses.md`) is signed by tagging `prereg-v1`. Anything
that measures credit or deposits in an event window, including model errors on treated
districts, runs only once that tag exists, so no outcome is seen before the design is fixed.
"""

from __future__ import annotations

import subprocess

from cri import config

TAG = "prereg-v1"


def is_signed() -> bool:
    """True when the repository has the `prereg-v1` tag."""
    try:
        out = subprocess.run(["git", "tag", "--list", TAG], cwd=config.REPO_ROOT,
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    return out.strip() == TAG


def require_signed(what: str) -> bool:
    """Print why `what` is not run and return False until the pre-registration is tagged."""
    if is_signed():
        return True
    print(f"not run: {what} looks at post-event credit or deposits, which waits for the "
          f"signed pre-registration (git tag {TAG}). Sign docs/00_hypotheses.md and tag it "
          "first; `git fetch --tags` if it was tagged elsewhere.")
    return False
