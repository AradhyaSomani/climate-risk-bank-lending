import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from cri.hazard import flood_grid
from cri.ml.susceptibility import features, train


def test_block_mean_and_distance():
    a = np.arange(16, dtype="float32").reshape(4, 4)
    a[0, 0] = np.nan
    b = features.block_mean(a, 2)
    assert b.shape == (2, 2) and b[0, 0] == pytest.approx((1 + 4 + 5) / 3)
    m = np.zeros((1, 5), dtype=bool)
    m[0, 0] = True
    d = features.distance_km(m, 0.01, lat0=0.0)
    assert d[0, 4] == pytest.approx(4 * 1.1132, rel=1e-3) and d[0, 0] == 0


def test_spatial_blocks_group_neighbouring_cells():
    g = train.blocks((10, 10), 0.5, 2.0)
    assert len(np.unique(g)) < 10
    assert g[0, 0] == g[0, 1] and g[0, 0] != g[9, 9]


def test_fill_and_out_of_fold_never_sees_its_block():
    x = np.array([[1.0, np.nan], [2.0, 4.0], [3.0, 6.0]])
    assert train.fill(x)[0, 1] == 5.0
    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, 2))
    y = (x[:, 0] + rng.normal(0, 0.5, 400) > 0).astype(int)
    groups = np.repeat(np.arange(8), 50)
    p = train.oof(train.logistic, x, y, groups, folds=4)
    assert np.isfinite(p).all() and np.corrcoef(p, y)[0, 1] > 0.5


def test_event_grid_shares(tmp_path, monkeypatch):
    # a 0.1-degree raster, 2 x 2 cells of a 0.2-degree grid: flooded in the left half
    res = 0.2
    left, top = 70.0, 30.0
    t = from_origin(left, top, 0.1, 0.1)
    flooded = np.zeros((4, 4), dtype="float32")
    flooded[:, :2] = 1
    flooded[3, 3] = np.nan
    perm = np.zeros((4, 4), dtype="float32")
    perm[0, 0] = 1
    tif = tmp_path / "ev.tif"
    with rasterio.open(tif, "w", driver="GTiff", width=4, height=4, count=2, dtype="float32",
                       crs="EPSG:4326", transform=t, nodata=np.nan) as dst:
        dst.write(flooded, 1)
        dst.write(perm, 2)
        dst.set_band_description(1, "flooded")
        dst.set_band_description(2, "jrc_perm_water")
    monkeypatch.setattr(flood_grid, "INDIA_BOUNDS", (left, top - 0.4, left + 0.4, top))
    monkeypatch.setattr(flood_grid, "india_grid",
                        lambda r: (from_origin(left, top, r, r), (int(0.4 / r), int(0.4 / r))))
    wet, obs = flood_grid.event_grid(tif, res)
    assert wet.shape == (2, 2)
    assert wet[0, 0] == pytest.approx(0.75)  # one of four pixels is permanent water
    assert wet[1, 0] == pytest.approx(1.0) and wet[0, 1] == 0
    assert obs[1, 1] == pytest.approx(0.75) and obs[0, 0] == 1


def test_subsample_keeps_at_most_max_cells():
    m = np.zeros(1000, dtype=bool)
    m[::2] = True
    s = train.subsample(m, 100, seed=0)
    assert s.sum() == 100 and not (s & ~m).any()
    assert train.subsample(m, None, 0) is m


def test_susceptibility_score_only_after_gate(tmp_path, monkeypatch):
    import pandas as pd

    from cri import config
    from cri.hazard import score

    pd.DataFrame({"district_id": [1, 2, 3, 4], "susceptibility": [0.1, 0.4, 0.2, 0.9]}
                 ).to_parquet(tmp_path / "susceptibility_district.parquet")
    runs = tmp_path / "model_runs.parquet"
    monkeypatch.setattr(config, "path", lambda key: runs)
    assert score.susceptibility_rows(tmp_path, [0.5, 0.75, 0.9]) is None  # no gate yet

    def gate(passed, when):
        return {"component": "susceptibility", "passed_gate": passed,
                "created_at": pd.Timestamp(when, tz="UTC")}

    pd.DataFrame([gate(True, "2026-01-01"), gate(False, "2026-02-01")]).to_parquet(runs)
    assert score.susceptibility_rows(tmp_path, [0.5, 0.75, 0.9]) is None  # latest failed
    pd.DataFrame([gate(False, "2026-01-01"), gate(True, "2026-02-01")]).to_parquet(runs)
    rows = score.susceptibility_rows(tmp_path, [0.5, 0.75, 0.9])
    assert set(rows.score_version) == {"susceptibility"} and set(rows.hazard_type) == {"flood"}
    assert rows.set_index("district_id").tier.to_dict() == {1: 1, 2: 2, 3: 1, 4: 4}
