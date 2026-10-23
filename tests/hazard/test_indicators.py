import pandas as pd
import pytest

from cri.hazard import indicators as ind

GFD_EVENTS = pd.DataFrame({"dfo_id": [1, 2, 3], "began": ["2005-07-01", "2010-08-01",
                                                        "2017-09-01"]})


def flood_rows():
    # district 1 floods in all three events, district 2 in one, district 3 is mapped but dry
    return pd.DataFrame({
        "event_id": ["GFD-1", "GFD-2", "GFD-3", "GFD-1", "GFD-1"],
        "district_id": [1, 1, 1, 2, 3],
        "source": "gfd",
        "flooded_share": [0.10, 0.30, 0.20, 0.05, 0.001],
        "flooded_built_share": [0.0, 0.2, 0.1, 0.0, 0.0],
        "flooded_crop_share": [0.2, 0.4, 0.3, 0.1, 0.0],
        "duration_days": [2.0, 6.0, 4.0, 1.0, 1.0],
    })


def cyclone_rows():
    return pd.DataFrame({
        "event_id": ["IMD-1999-001", "IMD-2019-002", "IMD-2019-002", "IMD-2021-003"],
        "district_id": [1, 1, 2, 2],
        "track_dist_km": [0.0, 50.0, 0.0, 300.0],
        "wind_kt_closest": [100.0, 40.0, 120.0, 90.0],
        "grade_closest": ["ESCS", "CS", "SuCS", "ESCS"],
        "within_radius": [True, True, True, False],
        "closest_time": pd.to_datetime(["1999-10-29", "2019-05-03", "2019-05-03",
                                        "2021-05-26"]).tz_localize("UTC"),
    })


def storms():
    return pd.DataFrame({
        "event_id": ["IMD-1999-001", "IMD-2019-002", "IMD-2021-003"],
        "start_time": pd.to_datetime(["1990-01-01", "2019-04-26", "2021-05-23"]),
        "end_time": pd.to_datetime(["1999-11-03", "2019-05-05", "2030-01-01"]),
        "landfall_district": [1.0, 2.0, None],
    })


def test_event_years():
    y = ind.event_years(["GFD-2", "IMD-2019-002", "X"], GFD_EVENTS)
    assert y["GFD-2"] == 2010 and y["IMD-2019-002"] == 2019 and pd.isna(y["X"])


def test_flood_indicators_known_answers():
    out = ind.flood_indicators(flood_rows(), [1, 2, 3, 4], hit_share=0.01, years=20.0)
    d1, d2, d3, d4 = (out.loc[i] for i in (1, 2, 3, 4))
    assert d1.flood_events_hit == 3 and d1.flood_events_per_decade == pytest.approx(1.5)
    assert d1.flood_mean_share == pytest.approx(0.2)
    assert d1.flood_max_share == pytest.approx(0.3)
    assert d1.flood_built_share == pytest.approx(0.1)
    assert d1.flood_duration_days == pytest.approx(4.0)
    assert d2.flood_events_hit == 1 and d2.flood_crop_share == pytest.approx(0.1)
    # mapped but below the hit share: no events, means are zero, worst share is kept
    assert d3.flood_events_hit == 0 and d3.flood_mean_share == 0
    assert d3.flood_max_share == pytest.approx(0.001) and d3.flood_events_mapped == 1
    assert d4.flood_events_mapped == 0 and d4.flood_max_share == 0


def test_cyclone_indicators_known_answers():
    out = ind.cyclone_indicators(cyclone_rows(), storms(), [1, 2, 3], radius_km=100,
                                 min_grade="CS", years=40.0)
    assert out.loc[1, "cyclone_storms_within"] == 2
    assert out.loc[1, "cyclone_storms_per_decade"] == pytest.approx(0.5)
    assert out.loc[1, "cyclone_max_wind_kt"] == 100 and out.loc[1, "cyclone_max_grade"] == "ESCS"
    # the 2021 storm passed 300 km away: it does not count for district 2's intensity
    assert out.loc[2, "cyclone_max_wind_kt"] == 120
    assert out.loc[2, "cyclone_max_grade_rank"] == 8
    assert out.loc[3, "cyclone_max_grade_rank"] == 0 and pd.isna(out.loc[3, "cyclone_max_grade"])
    assert out.loc[1, "cyclone_landfalls_per_decade"] == pytest.approx(0.25)
    assert out.loc[3, "cyclone_landfalls_per_decade"] == 0


def test_compute_with_cutoff_and_exclusion():
    base = pd.DataFrame({"district_id": [1, 2], "perm_water_share": [0.1, 0.0],
                         "elev_mean_m": [5.0, 50.0]})
    full = ind.compute(flood_rows(), cyclone_rows(), base, [2, 1], storms=storms(),
                       gfd_events=GFD_EVENTS).set_index("district_id")
    assert list(full.index) == [1, 2]
    assert full.loc[1, "flood_events_hit"] == 3 and "elev_mean_m" not in full
    assert full.loc[1, "gfd_record_years"] == pytest.approx(18.81, abs=0.01)
    assert full.loc[1, "imd_record_years"] == pytest.approx(40.0, abs=0.01)

    cut = ind.compute(flood_rows(), cyclone_rows(), base, [1, 2], storms=storms(),
                      before_year=2015, gfd_events=GFD_EVENTS).set_index("district_id")
    assert cut.loc[1, "flood_events_hit"] == 2
    assert cut.loc[1, "gfd_record_years"] == pytest.approx(14.87, abs=0.01)
    assert cut.loc[2, "cyclone_storms_within"] == 0  # Fani is after the cut-off
    assert cut.loc[2, "cyclone_landfalls_per_decade"] == 0
    assert cut.loc[1, "cyclone_landfalls_per_decade"] > 0

    ex = ind.compute(flood_rows(), None, None, [1, 2], exclude_events=["GFD-2"],
                     gfd_events=GFD_EVENTS).set_index("district_id")
    assert ex.loc[1, "flood_events_hit"] == 2 and ex.loc[1, "flood_max_share"] == 0.2
