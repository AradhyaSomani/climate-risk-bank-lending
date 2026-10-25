import geopandas as gpd
import pandas as pd
import pytest
import shapely
from shapely.geometry import box

from cri.hazard.cyclone_footprint import densify, storm_footprint
from cri.ingest.imd_tracks import grade_from_wind, grade_rank

METRIC = "EPSG:7755"


def test_grades_follow_imd_thresholds():
    g = grade_from_wind([10, 17, 27, 28, 34, 48, 64, 90, 119, 120, None]).tolist()
    assert g == ["L", "D", "D", "DD", "CS", "SCS", "VSCS", "ESCS", "ESCS", "SuCS", None]
    assert grade_rank("CS") > grade_rank("DD") and grade_rank(None) == -1


def test_densify_interpolates_in_time():
    t = pd.DataFrame({"time": pd.to_datetime(["2020-01-01 00:00", "2020-01-01 03:00"]),
                      "lat": [10.0, 13.0], "lon": [80.0, 80.0], "wind_kt": [30.0, 60.0]})
    d = densify(t, 30)
    assert len(d) == 7
    assert d.lat.iloc[2] == pytest.approx(11.0)
    assert d.wind_kt.iloc[-1] == 60


@pytest.fixture
def coast():
    # a strip of "land" east of 80E, two districts; the storm moves west onto it
    g = gpd.GeoDataFrame(
        {"district_id": [1, 2], "state": ["A", "A"]},
        geometry=[box(78.0, 10.0, 80.0, 11.0), box(78.0, 12.0, 80.0, 13.0)],
        crs="EPSG:4326",
    ).to_crs(METRIC)
    land = shapely.union_all(g.geometry.to_numpy())
    return g, land


def test_landfall_distance_and_closest_wind(coast, monkeypatch):
    from cri import config

    monkeypatch.setattr(config, "load", lambda name: {"cyclone": {"landfall_exclude_states": []}})
    g, land = coast
    track = pd.DataFrame({
        "time": pd.date_range("2020-05-01", periods=4, freq="6h"),
        "lat": [10.5] * 4, "lon": [83.0, 81.0, 79.5, 78.5], "wind_kt": [100, 90, 60, 30],
    })
    rows, summary = storm_footprint(track, g, land, minutes=30, max_report_km=500)
    rows = rows.set_index("district_id")
    assert rows.loc[1, "track_dist_km"] == 0  # the track crosses district 1
    assert rows.loc[2, "track_dist_km"] == pytest.approx(166, rel=0.05)  # 1.5 degrees north
    assert summary["landfall_district"] == 1
    lf = summary["landfall_time"]
    assert pd.Timestamp("2020-05-01 06:00") < lf < pd.Timestamp("2020-05-01 12:00")
    # strongest wind among the points over district 1 (it is entered at about 80E)
    assert 60 < rows.loc[1, "wind_kt_closest"] < 90
