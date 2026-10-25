import numpy as np
import pandas as pd
import pytest
from rasterio.transform import from_origin

from cri.hazard import baseline


def test_tile_names():
    jrc = baseline.jrc_tiles((76.0, 9.0, 77.0, 10.5))
    assert any("occurrence_70E_10N" in u for u in jrc)  # 70-80E, 0-10N
    assert any("occurrence_70E_20N" in u for u in jrc)  # 70-80E, 10-20N
    dem = baseline.dem_tiles((76.2, 9.1, 76.8, 9.9))
    assert len(dem) == 1 and "N09_00_E076_00" in dem[0]


def test_india_grid_aligns_with_jrc_tiles():
    t, shape = baseline.india_grid(0.005)
    # 70E and 40N tile corners fall on whole grid cells
    assert ((70 - t.c) / 0.005) == pytest.approx(round((70 - t.c) / 0.005))
    assert shape == (6300, 6000)


def test_slope_of_a_ramp():
    t = from_origin(76.0, 0.01, 0.001, 0.001)  # ~111 m cells at the equator
    elev = np.tile(np.arange(10, dtype=float) * 111.32, (10, 1))  # rises 111 m per cell east
    s = baseline.slope_deg(elev, t)
    assert s[5, 5] == pytest.approx(45, abs=0.5)


def test_zonal_mean_and_quantile():
    idx = np.array([[1, 1], [2, 0]])
    vals = np.array([[1.0, 3.0], [5.0, 100.0]])
    area = np.ones((2, 2))
    assert baseline.zonal(vals, idx, area, 2).tolist() == [2.0, 5.0]
    assert baseline.zonal_quantile(vals, idx, 2, 0.5).tolist() == [2.0, 5.0]


def test_flood_frequency():
    f = pd.DataFrame({"district_id": [1, 1, 1, 2], "source": "gfd",
                      "flooded_share": [0.2, 0.005, 0.3, 0.0]})
    out = baseline.flood_frequency(f, 0.01).set_index("district_id")
    assert out.loc[1, "gfd_events_hit"] == 2
    assert out.loc[1, "gfd_pixel_flood_count"] == pytest.approx(0.505)
    assert out.loc[2, "gfd_events_hit"] == 0
    assert out.loc[1, "gfd_events_hit_per_decade"] == pytest.approx(2 / 18.81 * 10, rel=0.01)
