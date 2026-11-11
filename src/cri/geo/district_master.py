"""District master (Phase 1 B, contract C1 `district_master`).

One row per Census 2011 district (640): code, name, state, population, area, urban share,
split flag and geometry. Geometry, names and state names come from the DataMeet Census 2011
boundary file that Person A's hazard tables already use, so switching A's code from the
shapefile to this table changes nothing but the source. Population and the urban share come
from the Census 2011 district table (data/raw/census2011, see docs/data_cards/census2011.md).

    python -m cri.geo.district_master            # build data/processed/district_master.parquet
    python -m cri.geo.district_master fetch      # download the Census 2011 district table
"""

from __future__ import annotations

import argparse
import logging
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

from cri import config
from cri.geo.districts import load_districts

log = logging.getLogger(__name__)

CENSUS_URL = ("https://raw.githubusercontent.com/nishusharma1608/India-Census-2011-Analysis/"
              "master/india-districts-census-2011.csv")
CENSUS_FILE = "india-districts-census-2011.csv"
COLUMNS = ["district_id", "name", "state", "state_code", "population", "area_km2",
           "urban_share", "split_flag", "geometry"]


def census_path() -> Path:
    return config.path("raw_layers.census2011") / CENSUS_FILE


def fetch_census(dest: Path | None = None) -> Path:
    dest = dest or census_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        urllib.request.urlretrieve(CENSUS_URL, dest)
    return dest


def read_census(path: Path | None = None) -> pd.DataFrame:
    """district_id, population, urban_share from the Census 2011 district table.

    The table has households, not persons, by rural and urban residence, so urban_share is
    urban households over all households (docs/data_cards/census2011.md).
    """
    raw = pd.read_csv(path or census_path())
    out = pd.DataFrame({
        "district_id": raw["District code"].astype(int),
        "population": raw["Population"].astype(int),
        "urban_share": raw["Urban_Households"] / raw["Households"],
    })
    if not out.district_id.is_unique:
        raise ValueError("Census table has repeated district codes")
    return out


def split_flag_ids(xw_cfg: dict | None = None) -> set[str]:
    """(state, Census 2011 name) pairs flagged in configs/crosswalk.yaml.

    A district is flagged when a later district took territory from it and from another
    Census 2011 district (so a weight of 1 to one parent is an approximation), or when its
    pre-2011 figures are shared by population although population is a poor guide.
    """
    xw_cfg = xw_cfg or config.load("crosswalk")
    flagged: set[tuple[str, str]] = set()
    for section in ("new_districts", "pre_2011_children"):
        for state, entries in (xw_cfg.get(section) or {}).items():
            for child, spec in entries.items():
                also = spec.get("also_from") or []
                if also:
                    flagged.update((state, n) for n in [spec["parent"], *also])
                    if section == "pre_2011_children":
                        flagged.add((state, child))
    for state, names in (xw_cfg.get("poor_population_proxy") or {}).items():
        flagged.update((state, n) for n in names)
    return flagged


def build_master(boundaries: gpd.GeoDataFrame, census: pd.DataFrame,
                 flagged: set[tuple[str, str]]) -> gpd.GeoDataFrame:
    gdf = boundaries.merge(census, on="district_id", how="left", validate="one_to_one")
    if gdf.population.isna().any():
        miss = gdf.loc[gdf.population.isna(), "name"].tolist()
        raise ValueError(f"No Census 2011 population for {miss}")
    known = set(zip(gdf.state, gdf.name, strict=True))
    unknown = flagged - known
    if unknown:
        raise ValueError(f"configs/crosswalk.yaml names districts not in the boundary file: "
                         f"{sorted(unknown)}")
    gdf["split_flag"] = [(s, n) in flagged for s, n in zip(gdf.state, gdf.name, strict=True)]
    gdf["population"] = gdf.population.astype(int)
    return gdf


def _state_codes(path: Path | None = None) -> pd.DataFrame:
    """Census 2011 state code (ST_CEN_CD) from the boundary file's attribute table."""
    raw = gpd.read_file(path or config.path("district_geometry.fallback"), ignore_geometry=True)
    raw = raw[raw.censuscode > 0]
    return pd.DataFrame({"district_id": raw.censuscode.astype(int),
                         "state_code": raw.ST_CEN_CD.astype(int)})


def build(out: Path | None = None) -> Path:
    out = out or config.path("district_geometry.preferred")
    # always from the shapefile: this table is what load_districts prefers once it exists
    boundaries = load_districts(config.path("district_geometry.fallback"))
    boundaries = boundaries.merge(_state_codes(), on="district_id", validate="one_to_one")
    master = build_master(boundaries, read_census(), split_flag_ids())
    master = gpd.GeoDataFrame(master[COLUMNS], geometry="geometry", crs=boundaries.crs)
    out.parent.mkdir(parents=True, exist_ok=True)
    master.to_parquet(out, index=False)
    log.info("district master: %d districts, %d flagged split, written to %s",
             len(master), int(master.split_flag.sum()), out)
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="build", choices=["build", "fetch"])
    a = p.parse_args(argv)
    print(fetch_census() if a.cmd == "fetch" else build())


if __name__ == "__main__":
    main()
