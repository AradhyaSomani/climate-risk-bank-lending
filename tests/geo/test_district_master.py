"""Phase 1 B: the district master (contract C1)."""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from cri.geo.district_master import build_master, split_flag_ids


def test_master_flags_and_population():
    bounds = gpd.GeoDataFrame({
        "district_id": [1, 2, 3], "name": ["Parent", "Child", "Other"],
        "state": ["Toy"] * 3, "area_km2": [1.0, 1.0, 1.0], "state_code": [7, 7, 7],
        "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)]}, crs="EPSG:4326")
    census = pd.DataFrame({"district_id": [1, 2, 3], "population": [10, 20, 30],
                           "urban_share": [0.1, 0.2, 0.3]})
    cfg = {"new_districts": {"Toy": {"NEWDIST": {"parent": "Other", "also_from": ["Parent"]}}}}
    m = build_master(bounds, census, split_flag_ids(cfg))
    assert m.set_index("name").split_flag.to_dict() == {"Parent": True, "Child": False,
                                                        "Other": True}
    with pytest.raises(ValueError, match="population"):
        build_master(bounds, census.iloc[:2], set())
