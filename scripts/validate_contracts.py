"""Validate contract tables. Exit code 1 if anything breaks its contract.

    python scripts/validate_contracts.py                 # every toy sample
    python scripts/validate_contracts.py C2 panel_credit_deposit path/to/file.parquet
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cri.contracts.validate import CONTRACTS_DIR, load_contract, validate_file  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) == 3:
        targets = [(argv[0], argv[1], argv[2])]
    elif not argv:
        targets = []
        for f in sorted(CONTRACTS_DIR.glob("C*_*.yaml")):
            code = f.name.split("_")[0]
            targets += [(code, t, None) for t in load_contract(code)["tables"]]
    else:
        print(__doc__)
        return 2

    failed = 0
    for code, table, path in targets:
        problems = validate_file(code, table, path)
        label = f"{code} {table} ({path or 'toy sample'})"
        if problems:
            failed += 1
            print(f"FAIL {label}")
            for p in problems:
                print(f"  - {p}")
        else:
            print(f"ok   {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
