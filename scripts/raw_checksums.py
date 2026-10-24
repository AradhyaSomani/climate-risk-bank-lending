"""Write or check SHA-256 checksums of the raw downloads (docs/data_access.md).

    python scripts/raw_checksums.py            # write docs/raw_checksums.sha256
    python scripts/raw_checksums.py --check    # compare data/raw with it

The file is in `sha256sum` format, so `sha256sum -c docs/raw_checksums.sha256` works too.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "raw_checksums.sha256"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def current() -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): sha256(p)
            for p in sorted(RAW.rglob("*")) if p.is_file() and not p.name.startswith(".")}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--check", action="store_true")
    a = p.parse_args(argv)
    now = current()
    if not a.check:
        OUT.write_text("".join(f"{h}  {name}\n" for name, h in now.items()))
        print(f"wrote {len(now)} checksums to {OUT.relative_to(ROOT)}")
        return 0
    want = {}
    for line in OUT.read_text().splitlines():
        h, name = line.split("  ", 1)
        want[name] = h
    bad = [k for k, v in want.items() if k in now and now[k] != v]
    missing = [k for k in want if k not in now]
    print(f"{len(want) - len(bad) - len(missing)} match, {len(bad)} differ, "
          f"{len(missing)} not downloaded")
    for k in bad:
        print("differs:", k)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
