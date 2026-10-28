import sys
import types

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from cri import config
from cri.hazard import flood_extent as fe


def write_tif(path, bands, transform, nodata=None, names=None, dtype="uint8"):
    count, h, w = bands.shape
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=count, dtype=dtype,
                       crs="EPSG:4326", transform=transform, nodata=nodata) as dst:
        dst.write(bands.astype(dtype))
        for i, n in enumerate(names or [], 1):
            dst.set_band_description(i, n)
    return path


@pytest.fixture
def two_districts():
    g = gpd.GeoDataFrame(
        {"district_id": [1, 2], "name": ["A", "B"], "state": ["Kerala", "Kerala"]},
        geometry=[box(76.0, 10.0, 76.5, 11.0), box(76.5, 10.0, 77.0, 11.0)],
        crs="EPSG:4326",
    )
    aea = "+proj=aea +lat_0=20 +lon_0=78 +lat_1=12 +lat_2=28"
    g["area_km2"] = g.geometry.to_crs(aea).area / 1e6
    return g


@pytest.fixture
def dirs(tmp_path, monkeypatch, two_districts):
    """Raw, interim and processed folders in tmp_path, two districts, no land cover."""
    real_path = config.path
    paths = {"interim": tmp_path / "interim", "processed": tmp_path / "processed",
             "raw_layers.sentinel1": tmp_path / "raw"}
    paths["raw_layers.sentinel1"].mkdir()
    monkeypatch.setattr(config, "path", lambda key: paths.get(key) or real_path(key))
    monkeypatch.setattr(fe, "load_districts", lambda: two_districts)
    real_load = config.load

    def load(name):
        cfg = real_load(name)
        if name == "hazard":
            cfg = {**cfg, "flood": {**cfg["flood"], "landcover": False},
                   "sentinel1": {**cfg["sentinel1"], "unet_model": str(tmp_path / "unet.pt")}}
        return cfg

    monkeypatch.setattr(config, "load", load)
    return paths


def test_export_names_with_and_without_parts(tmp_path):
    for name in ["FL-2018-KERALA_s1_otsu-0000000000-0000000000.tif",
                 "FL-2018-KERALA_s1_otsu-0000000000-0000032768.tif",
                 "FL-2018-KERALA_s1_backscatter.tif", "notes.tif", "FL-X_s1_other.tif"]:
        (tmp_path / name).touch()
    found = fe.s1_exports(tmp_path)
    assert sorted(found) == [("FL-2018-KERALA", "backscatter"), ("FL-2018-KERALA", "otsu")]
    assert len(found[("FL-2018-KERALA", "otsu")]) == 2
    assert fe.s1_exports(tmp_path / "missing") == {}


def test_prepare_mosaics_parts_and_marks_nodata(tmp_path):
    left = np.zeros((2, 10, 10))
    left[0, :, :5] = 1
    left[0, 0, 0] = 255  # no scene here
    right = np.ones((2, 10, 10))
    write_tif(tmp_path / "a.tif", left, from_origin(76.0, 11.0, 0.1, 0.1), nodata=255)
    write_tif(tmp_path / "b.tif", right, from_origin(77.0, 11.0, 0.1, 0.1), nodata=255)
    out = fe.prepare_s1([tmp_path / "a.tif", tmp_path / "b.tif"], "otsu", tmp_path / "m.tif")
    with rasterio.open(out) as src:
        assert src.descriptions == ("flooded", "jrc_perm_water")  # names from the band order
        assert (src.width, src.height) == (20, 10)
        flooded = src.read(1)
    assert np.isnan(flooded[0, 0]) and flooded[0, 1] == 1 and flooded[0, 15] == 1


def test_build_s1_writes_otsu_rows_next_to_existing_ones(dirs):
    flooded = np.zeros((2, 100, 100))
    flooded[0, :, :25] = 1  # half of district 1
    write_tif(dirs["raw_layers.sentinel1"] / "FL-2018-KERALA_s1_otsu.tif", flooded,
              from_origin(76.0, 11.0, 0.01, 0.01), nodata=255,
              names=["flooded", "jrc_perm_water"])
    out = fe.build_s1()
    df = pd.read_parquet(out[0]).set_index("district_id")
    assert set(df.source) == {"s1_otsu"} and set(df.event_id) == {"FL-2018-KERALA"}
    assert df.loc[1, "flooded_share"] == pytest.approx(0.5, abs=0.01)
    assert df.loc[2, "flooded_share"] == 0
    # a second run with nothing new keeps the table as it is
    assert pd.read_parquet(fe.build_s1()[0]).equals(pd.read_parquet(out[0]))


def test_build_s1_runs_the_unet_on_backscatter(dirs, tmp_path, monkeypatch):
    scene = np.full((3, 100, 100), -9999.0)
    scene[:, :, :50] = -20.0  # observed over district 1 only
    write_tif(dirs["raw_layers.sentinel1"] / "FL-2018-KERALA_s1_backscatter.tif", scene,
              from_origin(76.0, 11.0, 0.01, 0.01), nodata=-9999, dtype="float32",
              names=["VV", "VH", "jrc_perm_water"])
    (tmp_path / "unet.pt").touch()
    seen = {}

    def fake_predict(model, scene_path, out):  # every observed pixel is water
        with rasterio.open(scene_path) as src:
            seen["names"] = src.descriptions
            vv, profile = src.read(1), src.profile
        flooded = np.where(np.isnan(vv), 255, 1).astype("uint8")
        profile.update(count=2, dtype="uint8", nodata=255)
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(np.stack([flooded, flooded]))
            dst.set_band_description(1, "flooded")
            dst.set_band_description(2, "water")
        return out

    fake = types.ModuleType("cri.ml.flood_cnn.predict")
    fake.predict_geotiff = fake_predict
    monkeypatch.setitem(sys.modules, "cri.ml.flood_cnn.predict", fake)
    df = pd.read_parquet(fe.build_s1()[0]).set_index("district_id")
    assert seen["names"] == ("VV", "VH", "jrc_perm_water")
    assert set(df.source) == {"s1_unet"}
    # district 1 is all water; district 2 was never observed, so it has no row
    assert df.loc[1, "flooded_share"] == pytest.approx(1, abs=0.01)
    assert 2 not in df.index


def test_build_s1_keeps_otsu_rows_without_torch(dirs, tmp_path, monkeypatch):
    raw = dirs["raw_layers.sentinel1"]
    write_tif(raw / "FL-2018-KERALA_s1_otsu.tif", np.ones((2, 10, 10)),
              from_origin(76.0, 11.0, 0.1, 0.1), nodata=255)
    write_tif(raw / "FL-2018-KERALA_s1_backscatter.tif", np.full((3, 10, 10), -20.0),
              from_origin(76.0, 11.0, 0.1, 0.1), nodata=-9999, dtype="float32")
    (tmp_path / "unet.pt").touch()
    monkeypatch.setitem(sys.modules, "cri.ml.flood_cnn.predict", None)  # import fails
    df = pd.read_parquet(fe.build_s1()[0])
    assert set(df.source) == {"s1_otsu"}


def test_build_s1_without_exports_changes_nothing(dirs):
    assert fe.build_s1() == []
