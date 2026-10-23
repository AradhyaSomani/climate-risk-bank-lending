"""IMD RSMC New Delhi best track, from the parsed mirror kept by the `imdtrack` project.

The mirror is regenerated monthly from the IMD workbook and records the workbook URL and its
SHA-256 in manifest.json, which is saved next to the parquet files for provenance.

    python -m cri.ingest.imd_tracks            # download into data/raw/imd/
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import pandas as pd

from cri import config

MIRROR = "https://raw.githubusercontent.com/syedhamidali/imdtrack/main/data/{name}"
FILES = ("observations.parquet", "storms.parquet", "remarks.parquet", "manifest.json")

# IMD classes by maximum sustained wind (knots), weakest first. "L" marks fixes below
# depression strength (under 17 kt), which occur as storms decay over land.
GRADES = ["L", "D", "DD", "CS", "SCS", "VSCS", "ESCS", "SuCS"]
GRADE_MIN_KT = [0, 17, 28, 34, 48, 64, 90, 120]
# wind used for fixes that have a grade but no wind value (mid-point of the class)
GRADE_FILL_KT = {"L": 15, "D": 22, "DD": 30, "CS": 40, "SCS": 55, "VSCS": 76, "ESCS": 104,
                 "SuCS": 120}


def fetch(dest: Path | None = None, refresh: bool = False) -> Path:
    dest = dest or config.path("raw_layers.imd")
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        out = dest / name
        if refresh or not out.exists():
            urllib.request.urlretrieve(MIRROR.format(name=name), out)
    return dest


def manifest(src: Path | None = None) -> dict:
    src = src or config.path("raw_layers.imd")
    return json.loads((src / "manifest.json").read_text())


def grade_from_wind(wind_kt) -> pd.Series:
    w = pd.Series(wind_kt, dtype="float64")
    idx = pd.cut(w, bins=GRADE_MIN_KT + [float("inf")], right=False, labels=False)
    return pd.Series([GRADES[int(i)] if pd.notna(i) else None for i in idx], index=w.index,
                     dtype="object")


def grade_rank(grade: str | None) -> int:
    """Position in GRADES; -1 when the grade is unknown (no wind at that fix)."""
    return GRADES.index(grade) if grade in GRADES else -1


def load_tracks(src: Path | None = None) -> pd.DataFrame:
    """Best-track fixes, one row per fix, with QC-resolved times and suspect positions dropped.

    Columns: storm_id, name, basin, time (UTC), lat, lon, wind_kt, pressure, grade,
    wind_filled (True where the wind was missing and set from the grade's mid-point).
    """
    src = src or config.path("raw_layers.imd")
    obs = pd.read_parquet(src / "observations.parquet")
    obs = obs[~obs["pos_suspect"].fillna(False)].copy()
    obs["time"] = pd.to_datetime(obs["time_resolved"].fillna(obs["time"]))
    obs = obs.rename(columns={"wind": "wind_kt"})
    obs["grade"] = obs["grade"].astype("object").fillna(grade_from_wind(obs["wind_kt"]))
    obs["wind_filled"] = obs["wind_kt"].isna() & obs["grade"].isin(list(GRADE_FILL_KT))
    obs["wind_kt"] = obs["wind_kt"].fillna(obs["grade"].map(GRADE_FILL_KT))
    obs = obs.dropna(subset=["lat", "lon", "time"])
    obs = obs.sort_values(["storm_id", "time"]).drop_duplicates(["storm_id", "time"])
    cols = ["storm_id", "name", "basin", "time", "lat", "lon", "wind_kt", "pressure", "grade",
            "wind_filled"]
    return obs[cols].reset_index(drop=True)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args(argv)
    dest = fetch(refresh=a.refresh)
    m = manifest(dest)
    print(f"{dest}: {m['n_storms']} storms {m['year_min']}-{m['year_max']} from {m['source_url']}")


if __name__ == "__main__":
    main()
