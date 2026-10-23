"""Data test on the real IMD best track: skipped when data/raw/imd is not present."""

import pandas as pd
import pytest

from cri import config

RAW = config.path("raw_layers.imd") / "observations.parquet"
pytestmark = pytest.mark.skipif(not RAW.exists(), reason="IMD best track not downloaded")

# storm id, landfall district (Census 2011), reported crossing window (UTC)
CASES = [
    ("2019-002", 387, "2019-05-03 02:30", "2019-05-03 04:30"),  # Fani, Puri
    ("2020-001", 343, "2020-05-20 10:00", "2020-05-20 12:00"),  # Amphan, South 24 Parganas
    ("2014-006", 544, "2014-10-12 06:00", "2014-10-12 08:00"),  # Hudhud, Visakhapatnam
]


@pytest.mark.slow
def test_landfall_matches_imd_reports(tmp_path, monkeypatch):
    from cri.hazard import cyclone_footprint

    real_path = config.path

    def fake_path(key):
        return tmp_path if key == "processed" else real_path(key)

    monkeypatch.setattr(config, "path", fake_path)
    cyclone_footprint.build([c[0] for c in CASES])
    storms = pd.read_parquet(tmp_path / cyclone_footprint.STORMS_NAME).set_index("storm_id")
    for sid, district, t0, t1 in CASES:
        row = storms.loc[sid]
        assert row.landfall_district == district
        t = row.landfall_time.tz_convert(None)
        assert pd.Timestamp(t0) <= t <= pd.Timestamp(t1), (sid, t)
