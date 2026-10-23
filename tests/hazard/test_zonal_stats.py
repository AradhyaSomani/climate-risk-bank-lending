import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box

from cri.hazard.flood_extent import compare_sources
from cri.hazard.zonal_stats import flood_stats, pixel_area_km2


def test_pixel_area_matches_sphere():
    # one 1x1 degree cell at the equator on a sphere of the authalic radius: ~12,364 km2
    a = pixel_area_km2(from_origin(0, 1, 1, 1), 1)
    assert a[0, 0] == pytest.approx(12364, rel=1e-3)
    # cells shrink with latitude
    rows = pixel_area_km2(from_origin(0, 60, 1, 1), 60)
    assert rows[0, 0] < rows[-1, 0]


@pytest.fixture
def two_districts():
    # two 1 x 0.5 degree districts side by side near 10N
    g = gpd.GeoDataFrame(
        {"district_id": [1, 2]},
        geometry=[box(76.0, 10.0, 76.5, 11.0), box(76.5, 10.0, 77.0, 11.0)],
        crs="EPSG:4326",
    )
    aea = "+proj=aea +lat_0=20 +lon_0=78 +lat_1=12 +lat_2=28"
    g["area_km2"] = g.geometry.to_crs(aea).area / 1e6
    return g


def test_flooded_share_and_masks(two_districts):
    res = 0.01
    t = from_origin(76.0, 11.0, res, res)
    shape = (100, 100)
    flooded = np.zeros(shape, "float32")
    flooded[:, :25] = 1  # half of district 1 is flooded
    perm = np.zeros(shape, "float32")
    perm[:10, :25] = 1  # a tenth of that is permanent water
    duration = np.where(flooded > 0, 4.0, 0.0).astype("float32")
    clear = np.full(shape, 0.8, "float32")
    lc = np.zeros(shape, "uint8")
    lc[:, :50] = 40  # district 1 is all cropland
    out = flood_stats(
        {"flooded": flooded, "jrc_perm_water": perm, "duration": duration, "clear_perc": clear},
        t, two_districts, landcover=lc,
    ).set_index("district_id")
    assert out.loc[1, "flooded_share"] == pytest.approx(0.45, abs=0.01)
    assert out.loc[2, "flooded_share"] == 0
    assert out.loc[1, "mapped_share"] == pytest.approx(1, abs=0.01)
    assert out.loc[1, "duration_days"] == pytest.approx(4)
    assert np.isnan(out.loc[2, "duration_days"])
    assert out.loc[1, "clear_view_share"] == pytest.approx(0.8)
    assert out.loc[1, "flooded_crop_share"] == pytest.approx(0.45, abs=0.01)
    assert np.isnan(out.loc[1, "flooded_built_share"])


def test_nodata_outside_raster_lowers_mapped_share(two_districts):
    t = from_origin(76.0, 11.0, 0.01, 0.01)
    flooded = np.zeros((100, 100), "float32")
    flooded[50:, :] = np.nan  # southern half not observed
    out = flood_stats({"flooded": flooded}, t, two_districts).set_index("district_id")
    assert out.loc[1, "mapped_share"] == pytest.approx(0.5, abs=0.01)


def test_compare_sources_identical_and_disjoint():
    import pandas as pd

    a = pd.DataFrame({"district_id": [1, 2, 3, 4], "flooded_share": [0.3, 0.2, 0.0, 0.05]})
    same = compare_sources(a, a, hit_share=0.01)
    assert same["hit_iou"] == 1 and same["spearman"] == pytest.approx(1)
    b = a.assign(flooded_share=[0.0, 0.0, 0.4, 0.0])
    diff = compare_sources(a, b, hit_share=0.01)
    assert diff["hit_iou"] == 0 and diff["hit_only_b"] == [3]
