"""Load every processed table into PostGIS. Safe to run repeatedly.

    DATABASE_URL=postgresql://user@localhost:5432/cri python scripts/load_db.py
"""

from cri import runlog
from cri.db.load import load_all

if __name__ == "__main__":
    runlog.setup_logging()
    for table, n in load_all().items():
        print(f"{table:20s} {n:>8d}")
