"""District geometry for Person A's zonal statistics.

Reads B's district master (contract C1) when it exists, otherwise the DataMeet Census 2011
district shapefile, so A's hazard tables use the same Census 2011 district ids either way.

    python -m cri.geo.districts fetch     # download the DataMeet shapefile to data/raw/districts
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely import make_valid

from cri import config

DATAMEET_URL = "https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011/2011_Dist.{ext}"
SHAPEFILE_PARTS = ("shp", "shx", "dbf", "prj")


def fetch_datameet(dest: Path | None = None) -> Path:
    dest = dest or config.path("raw_layers.districts")
    dest.mkdir(parents=True, exist_ok=True)
    for ext in SHAPEFILE_PARTS:
        out = dest / f"2011_Dist.{ext}"
        if not out.exists():
            urllib.request.urlretrieve(DATAMEET_URL.format(ext=ext), out)
    return dest / "2011_Dist.shp"


def load_districts(path: Path | None = None) -> gpd.GeoDataFrame:
    """GeoDataFrame with district_id, name, state, area_km2, geometry (EPSG:4326)."""
    path = path or config.district_geometry_path()
    if path.suffix == ".parquet":
        gdf = gpd.read_parquet(path)[["district_id", "name", "state", "geometry"]]
    else:
        raw = gpd.read_file(path)
        cols = {"censuscode": "district_id", "DISTRICT": "name", "ST_NM": "state"}
        gdf = raw.rename(columns=cols)
        gdf = gdf.loc[gdf["district_id"] > 0, ["district_id", "name", "state", "geometry"]]
    gdf = gdf.to_crs(config.load("project")["crs"]["geographic"])
    gdf["geometry"] = [g if g.is_valid else make_valid(g) for g in gdf.geometry]
    gdf["district_id"] = gdf["district_id"].astype(int)
    gdf["area_km2"] = equal_area_km2(gdf)
    return gdf.sort_values("district_id").reset_index(drop=True)


def equal_area_km2(gdf: gpd.GeoDataFrame) -> np.ndarray:
    crs = config.load("project")["crs"]["equal_area"]
    return gdf.geometry.to_crs(crs).area.to_numpy() / 1e6


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cmd", choices=["fetch"])
    p.parse_args(argv)
    print(fetch_datameet())


if __name__ == "__main__":
    main()
