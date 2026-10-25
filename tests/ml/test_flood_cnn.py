import numpy as np
import pandas as pd
import pytest

from cri.ml.flood_cnn import baselines as bl
from cri.ml.flood_cnn import data


def test_otsu_splits_a_bimodal_histogram():
    rng = np.random.default_rng(0)
    db = np.r_[rng.normal(-25, 1, 5000), rng.normal(-8, 1, 5000)]
    t = bl.otsu_threshold(db)
    assert -22.5 < t < -10.5  # anywhere in the gap between the modes is optimal
    assert np.isnan(bl.otsu_threshold(np.array([np.nan, np.nan])))


def test_otsu_water_ignores_nodata():
    rng = np.random.default_rng(1)
    db = np.r_[rng.normal(-25, 1, 500), rng.normal(-8, 1, 500), [np.nan] * 10]
    w = bl.otsu_water(db)
    assert w[:500].mean() > 0.99 and w[500:1000].mean() < 0.01 and not w[-10:].any()


def test_change_detection():
    pre = np.array([-8.0, -8.0, -24.0, -9.0])
    post = np.array([-22.0, -9.0, -24.0, -20.0])
    # first: dropped 14 dB and is dark; second: no drop; third: permanent water; fourth: drop
    assert bl.change_detection(pre, post, 3.0, water_db=-15).tolist() == [True, False, False,
                                                                          True]


def test_confusion_scores_and_event_means():
    label = np.array([1, 1, 0, 0, -1])
    pred = np.array([1, 0, 1, 0, 1])
    c = bl.confusion(pred, label)
    assert c == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}  # the -1 pixel is ignored
    s = bl.scores(c)
    assert s["iou_water"] == pytest.approx(1 / 3) and s["f1_water"] == pytest.approx(0.5)
    rows = pd.DataFrame([{"event": "A", **c}, {"event": "A", **c},
                         {"event": "B", "tp": 4, "fp": 0, "fn": 0, "tn": 4}])
    out = bl.by_event(rows).set_index("event")
    assert out.loc["A", "iou_water"] == pytest.approx(1 / 3)
    assert out.loc["mean", "iou_water"] == pytest.approx((1 / 3 + 1) / 2)  # events weigh equally


def test_split_by_event_has_no_leak():
    t = pd.DataFrame({"chip": ["India_1", "India_2", "Bolivia_1", "USA_1", "Sri-Lanka_1"],
                      "event": ["India", "India", "Bolivia", "USA", "Sri-Lanka"]})
    s = data.split_chips(t, ["India", "Bolivia"], ["Sri-Lanka"])
    assert s == {"train": ["USA_1"], "val": ["Sri-Lanka_1"],
                 "test": ["India_1", "India_2", "Bolivia_1"]}
    with pytest.raises(ValueError):
        data.split_chips(t, ["India"], ["India"])


def test_shuffle_labels_moves_masks_between_patches():
    rng = np.random.default_rng(0)
    x = rng.random((6, 2, 4, 4)).astype("float32")
    y = np.stack([np.full((4, 4), i % 2, dtype="int8") for i in range(6)])
    y[:, 0, 0] = np.arange(6)  # tag each mask so a permutation is visible
    meta = pd.DataFrame({"chip": list("abcdef")})
    s = data.shuffle_labels(data.Split(x, y, meta), seed=3)
    assert s.x is x and s.meta is meta  # inputs untouched
    assert sorted(s.y[:, 0, 0].tolist()) == list(range(6))  # the same masks...
    assert s.y[:, 0, 0].tolist() != list(range(6))  # ...on other patches
    for m in s.y:
        assert (m == y[m[0, 0]]).all()  # each mask moved whole


def test_patches_and_scaling():
    x = np.zeros((2, 512, 512), dtype="float32")
    y = np.zeros((512, 512), dtype="int8")
    assert len(list(data.to_patches(x, y, 256))) == 4
    assert data.scale_db(np.array([-50.0, -15.0, 5.0]), "vv").tolist() == [0.0, 0.5, 1.0]


def test_unet_shapes_loss_and_tiled_prediction():
    torch = pytest.importorskip("torch")
    from cri.ml.flood_cnn.model import UNet, augment, dice_ce_loss
    from cri.ml.flood_cnn.predict import predict_array

    m = UNet(in_channels=2, base=4, depth=2)
    x = torch.randn(2, 2, 64, 64)
    logits = m(x)
    assert logits.shape == (2, 2, 64, 64)
    y = torch.randint(0, 2, (2, 64, 64))
    y[:, :8] = -1
    loss = dice_ce_loss(logits, y, torch.tensor([1.0, 2.0]))
    loss.backward()
    assert torch.isfinite(loss)
    xa, ya = augment(x, y, torch.Generator().manual_seed(0))
    assert xa.shape == x.shape and (ya == -1).sum() == (y == -1).sum()
    out = predict_array(m.eval(), np.random.rand(2, 100, 150).astype("float32"), tile=64,
                        overlap=16)
    assert out.shape == (100, 150) and out.dtype == bool
