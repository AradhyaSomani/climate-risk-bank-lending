"""Land outside India (Natural Earth 10 m land minus India), used to tell a landfall from a
storm that enters India overland from Bangladesh or Myanmar.

Natural Earth is public domain.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import geopandas as gpd
import shapely

from cri import config

NE_LAND_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_10m_land.geojson"
)
REGION = (50.0, -5.0, 110.0, 40.0)


def fetch(dest: Path | None = None) -> Path:
    dest = dest or config.path("raw_layers.natural_earth")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "ne_10m_land.geojson"
    if not out.exists():
        urllib.request.urlretrieve(NE_LAND_URL, out)
    return out


def land_metric(metric_crs):
    land = gpd.read_file(fetch()).clip(shapely.box(*REGION)).to_crs(metric_crs)
    return shapely.union_all(land.geometry.to_numpy())


def coastal_mask(districts_metric: gpd.GeoDataFrame, within_km: float = 5.0):
    """True for districts within `within_km` of the sea (Natural Earth coastline)."""
    land = land_metric(districts_metric.crs)
    region = gpd.GeoSeries([shapely.box(*REGION)], crs="EPSG:4326").to_crs(districts_metric.crs)
    sea = shapely.difference(region.iloc[0], land)
    return shapely.distance(districts_metric.geometry.to_numpy(), sea) <= within_km * 1000


def foreign_land(india_metric, metric_crs, buffer_km: float = 5.0):
    """Land in the region that is not within buffer_km of India, in the metric CRS."""
    land = land_metric(metric_crs)
    return shapely.difference(land, shapely.buffer(india_metric, buffer_km * 1000))
