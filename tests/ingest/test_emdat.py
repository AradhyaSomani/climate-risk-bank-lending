import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from cri.geo.names import best_match, normalise
from cri.ingest import emdat


def test_normalise_variants():
    assert normalise("Orissa") == "odisha"
    assert normalise("Andaman & Nicobar Islands") == normalise("Andaman and Nicobar Islands")
    assert normalise("Ernakulam District") == "ernakulam"
    assert normalise("Y.S.R.") == "y s r"


def test_best_match_methods():
    cands = {"thiruvananthapuram": 601, "kozhikode": 591}
    assert best_match("Thiruvananthapuram", cands)[1] == "exact"
    assert best_match("Thiruvanathapuram", cands)[1] == "fuzzy"
    assert best_match("Mumbai", cands) is None


@pytest.fixture
def districts():
    return gpd.GeoDataFrame(
        {"district_id": [595, 598, 387], "name": ["Ernakulam", "Alappuzha", "Puri"],
         "state": ["Kerala", "Kerala", "Odisha"]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)], crs="EPSG:4326",
    )


def _export(rows):
    base = {"ISO": "IND", "Disaster Subtype": "", "Location": None, "Admin Units": None,
            "GADM Admin Units": None, "Start Day": None, "End Day": None}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_geocode_levels_and_review(districts):
    df = _export([
        {"DisNo.": "2018-0001-IND", "Disaster Type": "Flood",
         "GADM Admin Units": json.dumps([{"gid_1": "IND.18_1", "name_1": "Kerala"},
                                         {"gid_2": "x", "name_2": "Ernakulam"},
                                         {"gid_2": "y", "name_2": "Alapuzha"}])},
        {"DisNo.": "2019-0002-IND", "Disaster Type": "Storm",
         "Admin Units": json.dumps([{"adm1_code": 1, "adm1_name": "Orissa"}])},
        {"DisNo.": "2005-0003-IND", "Disaster Type": "Flood", "Location": "Puri district, Orissa"},
    ])
    geo, review = emdat.geocode(df, districts)
    r1 = geo[geo.disno == "2018-0001-IND"]
    assert set(r1.district_id) == {595, 598} and (r1.geo_level == "district").all()
    assert review.loc[review.name == "Alapuzha", "method"].iloc[0] == "fuzzy"
    r2 = geo[geo.disno == "2019-0002-IND"]
    assert r2.geo_level.tolist() == ["state"] and r2.state.iloc[0] == "Odisha"
    r3 = geo[geo.disno == "2005-0003-IND"]
    assert 387 in set(r3.district_id.dropna())


def test_partial_dates():
    assert emdat._date(2018, 8, None, end=True) == (pd.Timestamp("2018-08-31"), "month")
    assert emdat._date(2018, None, None, end=False) == (pd.Timestamp("2018-01-01"), "year")
    assert emdat._date(2018, 8, 16, end=False) == (pd.Timestamp("2018-08-16"), "day")


def test_link_events_by_name_and_overlap():
    rec = pd.DataFrame({
        "hazard_type": ["cyclone", "flood"], "event_name": ["Cyclone 'Fani'", None],
        "start_date": pd.to_datetime(["2019-05-02", "2015-11-15"]),
        "end_date": pd.to_datetime(["2019-05-04", "2015-12-05"]),
    })
    storms = pd.DataFrame({"storm_id": ["2019-002"], "name": ["FANI"],
                           "start_time": pd.to_datetime(["2019-04-26"]),
                           "end_time": pd.to_datetime(["2019-05-04"]),
                           "landfall_time": pd.to_datetime(["2019-05-03"])})
    gfd = pd.DataFrame({"dfo_id": [4309, 4251],
                        "began": pd.to_datetime(["2015-11-10", "2015-05-17"]),
                        "ended": pd.to_datetime(["2015-12-04", "2015-05-21"])})
    out = emdat.link_events(rec, storms, gfd)
    assert out.imd_event_id.iloc[0] == "IMD-2019-002"
    assert out.gfd_event_id.iloc[1] == "GFD-4309"
