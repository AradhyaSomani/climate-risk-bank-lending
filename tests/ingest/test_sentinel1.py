from unittest import mock

import pytest
from shapely.geometry import box

from cri import config
from cri.ingest import sentinel1 as s1


def test_presets_cover_the_events_without_a_gfd_map():
    kerala = s1.preset("FL-2018-KERALA")
    assert kerala["pre"][1] < "2018-05-29" < kerala["post"][0]  # reference before the monsoon
    assert len(kerala["backscatter_bbox"]) == 4
    assert s1.preset("FL-NOT-THERE") == {}


def test_event_area_is_the_land_of_the_event_states():
    if not config.district_geometry_path().exists():
        pytest.skip("district boundaries not downloaded")
    w, s, e, n = s1.event_area("FL-2018-KERALA").bounds
    assert 74.5 < w < 75.2 and 8.0 < s < 8.5 and 77.2 < e < 77.6 and 12.6 < n < 13.0
    cut = s1.event_area("FL-2018-KERALA", (76.2, 9.0, 76.9, 10.3))
    assert cut.bounds[0] >= 76.2 and cut.bounds[3] <= 10.3


def test_export_goes_to_drive_with_a_project_and_nodata(monkeypatch):
    fake_ee = mock.MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "ee", fake_ee)
    monkeypatch.setattr(s1, "event_area", lambda event, bbox=None: box(76, 9, 77, 10))
    s1.main(["--event", "FL-2018-KERALA", "--project", "my-ee-project"])
    fake_ee.Initialize.assert_called_with(project="my-ee-project")
    kw = fake_ee.batch.Export.image.toDrive.call_args.kwargs
    assert kw["folder"] == "cri-sentinel1" and kw["fileNamePrefix"] == "FL-2018-KERALA_s1_otsu"
    assert kw["formatOptions"] == {"noData": 255} and kw["scale"] == 30
    fake_ee.batch.Export.image.toCloudStorage.assert_not_called()


def test_check_counts_scenes_and_exports_nothing(monkeypatch, capsys):
    fake_ee = mock.MagicMock()
    fake_ee.ImageCollection.return_value.filterBounds.return_value.filter.return_value \
        .filter.return_value.filter.return_value.filterDate.return_value.size.return_value \
        .getInfo.return_value = 3
    monkeypatch.setitem(__import__("sys").modules, "ee", fake_ee)
    monkeypatch.setattr(s1, "event_area", lambda event, bbox=None: box(76, 9, 77, 10))
    s1.main(["--event", "FL-2018-KERALA", "--project", "p", "--check"])
    out = capsys.readouterr().out
    assert "ASCENDING" in out and "DESCENDING" in out and " 3 " in out
    fake_ee.batch.Export.image.toDrive.assert_not_called()


def test_backscatter_without_a_box_is_refused(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "ee", mock.MagicMock())
    with pytest.raises(SystemExit):
        s1.main(["--event", "FL-2015-CHENNAI", "--kind", "backscatter", "--bbox"])
