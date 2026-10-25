"""Validate contract tables. Exit code 1 if anything breaks its contract.

    python scripts/validate_contracts.py                 # every toy sample
    python scripts/validate_contracts.py C2 panel_credit_deposit path/to/file.parquet

Same as `python -m cri.contracts`; this wrapper runs from a checkout without installing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cri.contracts import main  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) not in (0, 3):
        print(__doc__)
        sys.exit(2)
    sys.exit(main(args or ["--samples"]))
