"""Phase 1 D: district-quarter controls, on small synthetic tables."""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from cri.exposure.controls import (
    build_controls,
    ntl_quarterly,
    rain_quarterly,
    read_ee_tables,
    waiver_flags,
)
from cri.ingest.ee_controls import band_name, district_batches, periods

Q = pd.Timestamp
QUARTERS = [Q("2017-03-31"), Q("2017-06-30"), Q("2017-09-30"), Q("2017-12-31")]


def _master():
    return pd.DataFrame({"district_id": [1, 2, 3], "state": ["A", "A", "B"],
                         "population": [10, 20, 30], "urban_share": [0.1, 0.2, 0.3]})


def _census():
    return pd.DataFrame({"District code": [1, 2, 3], "Population": [10, 20, 30],
                         "Literate": [5, 10, 30], "Workers": [4, 10, 10],
                         "Cultivator_Workers": [1, 2, 0], "Agricultural_Workers": [1, 3, 0]})


def _write_rain(folder, values):
    """values: {district_id: {"p2017_01": mm, ...}} split over two batch files."""
    ids = sorted(values)
    for k, part in enumerate([ids[:1], ids[1:]], start=1):
        rows = [{"system:index": str(i), "district_id": i, **values[i], ".geo": "{}"}
                for i in part]
        pd.DataFrame(rows).to_csv(folder / f"rain_batch{k}.csv", index=False)


def test_read_ee_tables_long_and_batches(tmp_path):
    _write_rain(tmp_path, {1: {"p2017_01": 1.0, "p2017_02": 2.0},
                           2: {"p2017_01": 3.0, "p2017_02": None}})
    t = read_ee_tables(tmp_path, "rain")
    assert len(t) == 4 and set(t.district_id) == {1, 2}
    assert t.period.min() == Q("2017-01-01")
    assert read_ee_tables(tmp_path, "ntl_viirs").empty


def test_rain_needs_three_months_and_anomaly_uses_normal():
    rows = []
    for year, mm in [(2015, 10.0), (2016, 30.0), (2017, 40.0)]:
        for month in (1, 2, 3):
            rows.append({"district_id": 1, "period": Q(f"{year}-{month:02d}-01"), "value": mm})
    rows.append({"district_id": 1, "period": Q("2017-04-01"), "value": 5.0})  # only 1 month
    q = rain_quarterly(pd.DataFrame(rows), (2015, 2016)).set_index("quarter_end")
    assert q.rain_mm[Q("2017-03-31")] == pytest.approx(120.0)
    # normal = mean of 30 and 90 = 60, so 120 is +100 %
    assert q.rain_anom[Q("2017-03-31")] == pytest.approx(1.0)
    assert pd.isna(q.rain_mm[Q("2017-06-30")])


def test_ntl_quarter_mean():
    m = pd.DataFrame({"district_id": [1, 1, 1], "value": [1.0, 2.0, 6.0],
                      "period": [Q("2017-01-01"), Q("2017-02-01"), Q("2017-03-01")]})
    assert ntl_quarterly(m).ntl_viirs.iloc[0] == pytest.approx(3.0)


def test_waiver_flags():
    waivers = [
        {"state": "A", "announced": "2017-04-04", "scope": "all lenders"},
        {"state": "B", "announced": "2017-08-01", "scope": "cooperative banks only"},
    ]
    w = waiver_flags(waivers, _master(), QUARTERS).set_index(["district_id", "quarter_end"])
    assert w.waiver_commercial[(1, Q("2017-06-30"))]
    assert not w.waiver_commercial[(3, Q("2017-09-30"))]
    assert w.waiver_coop_only[(3, Q("2017-09-30"))]
    assert pd.isna(w.quarters_since_waiver[(1, Q("2017-03-31"))])
    assert w.quarters_since_waiver[(1, Q("2017-12-31"))] == 2
    assert pd.isna(w.quarters_since_waiver[(3, Q("2017-12-31"))])
    with pytest.raises(ValueError, match="unknown"):
        waiver_flags([{"state": "Z", "announced": "2017-01-01", "scope": "x"}], _master(),
                     QUARTERS)


def test_build_controls_without_earth_engine_tables(tmp_path):
    cfg = {"loan_waivers": [{"state": "ALL", "announced": "2017-02-01", "scope": "all"}]}
    c = build_controls(_master(), _census(), tmp_path, cfg, QUARTERS, "data-v0-test")
    assert len(c) == 3 * 4
    assert not c.duplicated(["district_id", "quarter_end"]).any()
    assert c.rain_mm.isna().all() and c.ntl_harmonized.isna().all()
    one = c[c.district_id == 1].iloc[0]
    assert one.ag_worker_share_2011 == pytest.approx(0.5)
    assert one.literacy_2011 == pytest.approx(0.5)
    assert c.loc[c.quarter_end == QUARTERS[0], "waiver_commercial"].all()


def test_build_controls_with_rain(tmp_path):
    months = {f"p2017_{m:02d}": 10.0 for m in range(1, 13)}
    _write_rain(tmp_path, {1: months, 2: months, 3: months})
    c = build_controls(_master(), _census(), tmp_path, {"rain_normal": [2017, 2017]},
                       QUARTERS, "data-v0-test")
    assert (c.rain_mm == 30.0).all()
    assert (c.rain_anom == 0.0).all()


def test_periods_and_band_names():
    months = periods("2012-04-01", "2012-07-01", "month")
    assert [band_name(t, "month") for t in months] == ["p2012_04", "p2012_05", "p2012_06"]
    assert [band_name(t, "year") for t in periods("2000-01-01", "2002-01-01", "year")] == \
        ["p2000", "p2001"]


def test_district_batches_split_and_keep_ids():
    m = gpd.GeoDataFrame({"district_id": [3, 1, 2],
                          "geometry": [box(i, 0, i + 1, 1) for i in range(3)]}, crs="EPSG:4326")
    b = district_batches(m, size=2, simplify_deg=0.01)
    assert [len(x["features"]) for x in b] == [2, 1]
    assert [f["properties"]["district_id"] for x in b for f in x["features"]] == [1, 2, 3]


def test_sources_cut_overlapping_parts():
    from cri.ingest.ee_controls import sources

    spec = {"start": "2000-01-01", "end": "2022-01-01",
            "collections": [{"id": "dmsp", "end": "2014-01-01"},
                            {"id": "viirs", "start": "2014-01-01"}]}
    assert sources(spec) == [("dmsp", "2000-01-01", "2014-01-01"),
                             ("viirs", "2014-01-01", "2022-01-01")]
    assert sources({"start": "2014-01-01", "end": "2026-07-01", "collection": "v"}) == \
        [("v", "2014-01-01", "2026-07-01")]
    # a part entirely outside the window is dropped
    assert sources({"start": "2015-01-01", "end": "2016-01-01",
                    "collections": [{"id": "dmsp", "end": "2014-01-01"}, "viirs"]}) == \
        [("viirs", "2015-01-01", "2016-01-01")]
