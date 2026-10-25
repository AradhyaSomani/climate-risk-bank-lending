import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from cri import config
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


def test_read_export_keeps_floods_and_tropical_cyclones_only(tmp_path):
    path = tmp_path / "export.csv"
    pd.DataFrame({
        "DisNo.": ["2018-0001-IND", "2", "3", "4", "5", "6"],
        "ISO": ["IND", "IND", "IND", "IND", "IND", "NPL"],
        "Disaster Type": ["Flood", "Storm", "Storm", "Glacial lake outburst flood",
                          "Drought", "Flood"],
        "Disaster Subtype": ["Flash flood", "Tropical cyclone", "Lightning/Thunderstorms",
                             "", "Drought", "Riverine flood"],
    }).to_csv(path, index=False)
    assert emdat.read_export(path)["DisNo."].astype(str).tolist() == ["2018-0001-IND", "2", "4"]


def test_gid_states_reads_names_and_votes_for_unnamed_gids(districts):
    df = _export([
        {"GADM Admin Units": json.dumps([{"gid_1": "IND.17_1", "name_1": "Kerala"}])},
        # GADM files Indian Kashmir under Z01.14_1, which never appears as a state
        {"GADM Admin Units": json.dumps([{"gid_2": "Z01.14.3_1", "name_2": "Ernakulam"},
                                         {"gid_2": "Z01.14.5_1", "name_2": "Alappuzha"}])},
    ])
    ids = {normalise(n): i for n, i in zip(districts.name, districts.district_id, strict=True)}
    id_state = dict(zip(districts.district_id, districts.state, strict=True))
    assert emdat.gid_states(df) == {"IND.17_1": "Kerala"}
    assert emdat.gid_states(df, ids, id_state) == {"IND.17_1": "Kerala", "Z01.14_1": "Kerala"}


def test_admin_units_takes_the_state_from_the_gid():
    row = pd.Series({"GADM Admin Units": json.dumps([
        {"gid_1": "IND.26_1", "name_1": "Odisha"}, {"gid_2": "IND.17.3_1", "name_2": "Idukki"}])})
    states, pairs = emdat.admin_units(row, {"IND.17_1": "Kerala", "IND.26_1": "Odisha"})
    assert states == ["Odisha"] and pairs == [("Idukki", "Kerala")]


def test_parse_location_applies_bracketed_states():
    states = {"odisha": "odisha", "west bengal": "west bengal", "telangana": "andhra pradesh"}
    found, pairs = emdat.parse_location(
        "Puri, Khordha districts (Orissa province), Kolkata (West Bengal), Telangana", states)
    assert found == ["odisha", "west bengal", "andhra pradesh"]
    assert pairs == [("Puri", "odisha"), ("Khordha", "odisha"), ("Kolkata", "west bengal")]


def test_geocode_aliases_state_renames_and_country_fallback(districts):
    aliases = ({"telangana": "Odisha"}, {"kerala": {"cochin": "Ernakulam"}})
    df = _export([
        # a later name inside its state, and a state rename
        {"DisNo.": "1", "Disaster Type": "Flood",
         "GADM Admin Units": json.dumps([{"gid_1": "IND.17_1", "name_1": "Kerala"},
                                         {"gid_1": "IND.32_1", "name_1": "Telangana"},
                                         {"gid_2": "IND.17.1_1", "name_2": "Cochin"}])},
        # an alias whose state is not given, and a state that only the free text names
        {"DisNo.": "2", "Disaster Type": "Flood", "Location": "Cochin; Odisha",
         "Admin Units": json.dumps([{"adm2_code": 1, "adm2_name": "Cochin"}])},
        {"DisNo.": "3", "Disaster Type": "Flood", "Location": "Administrative unit not available"},
    ])
    geo, review = emdat.geocode(df, districts, aliases)
    r1 = geo[geo.disno == "1"].set_index("geo_level")
    assert r1.loc["district", "district_id"] == 595
    assert r1.loc["district", "match_method"] == "alias"
    assert r1.loc["state", "state"] == "Odisha"  # Telangana mapped through the state alias
    r2 = geo[geo.disno == "2"]
    assert r2.match_method.tolist() == ["alias_national", "state_only"]
    assert r2.state.tolist() == ["Kerala", "Odisha"]
    assert geo[geo.disno == "3"].geo_level.tolist() == ["country"]
    assert set(review.method) == {"alias", "alias_national", "unmatched"}


def test_alias_targets_are_census_districts():
    if not config.district_geometry_path().exists():
        pytest.skip("district boundaries not downloaded")
    from cri.geo.districts import load_districts

    d = load_districts()
    names = {normalise(s): {normalise(n) for n in g.name} for s, g in d.groupby("state")}
    state_alias, aliases = emdat.load_aliases()
    assert {normalise(s) for s in state_alias.values()} <= set(names)
    bad = [(st, a, t) for st, m in aliases.items() for a, t in m.items()
           if normalise(t) not in names.get(st, set())]
    assert not bad


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
