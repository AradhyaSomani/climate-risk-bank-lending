"""Apply a trained U-Net to a full Sentinel-1 scene (Phase 2B-B cross-domain check).

The scene is a GeoTIFF with VV and VH bands in dB, such as the Kerala August 2018 export
from `cri.ingest.sentinel1` (band names `VV`, `VH`). The output GeoTIFF has the bands
`flooded` (model water minus JRC permanent water, if the scene carries `jrc_perm_water`) and
`water`, so `cri.hazard.zonal_stats.event_flood_extent` can read it with source `s1_unet`.

    python -m cri.ml.flood_cnn.predict data/interim/flood_cnn/sar_base16.pt scene.tif out.tif
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio
import torch

from cri.ml.flood_cnn.data import scale_db
from cri.ml.flood_cnn.model import UNet


def load_model(path: Path) -> tuple[UNet, list[str]]:
    ck = torch.load(path, map_location="cpu", weights_only=False)
    cfg = ck["config"]
    chans = cfg["data"]["channels"]
    m = UNet(len(chans), 2, cfg["model"]["base_channels"], cfg["model"]["depth"])
    m.load_state_dict(ck["state_dict"])
    m.eval()
    return m, chans


@torch.no_grad()
def predict_array(model: UNet, x: np.ndarray, tile: int = 512, overlap: int = 64) -> np.ndarray:
    """Water mask for a (channels, H, W) array, tiled with overlap; edges are padded."""
    _, h, w = x.shape
    step = tile - overlap

    def padded(n: int) -> int:
        return -(-max(n - overlap, 1) // step) * step + overlap

    ph, pw = padded(h), padded(w)
    xp = np.pad(x, ((0, 0), (0, ph - h), (0, pw - w)), mode="reflect")
    votes = np.zeros((ph, pw), dtype="float32")
    count = np.zeros((ph, pw), dtype="float32")
    for r in range(0, ph - overlap, step):
        for c in range(0, pw - overlap, step):
            patch = torch.from_numpy(xp[None, :, r:r + tile, c:c + tile].copy())
            p = torch.softmax(model(patch), 1)[0, 1].numpy()
            votes[r:r + tile, c:c + tile] += p
            count[r:r + tile, c:c + tile] += 1
    return (votes / np.maximum(count, 1))[:h, :w] > 0.5


def predict_geotiff(model_path: Path, scene: Path, out: Path) -> Path:
    model, chans = load_model(model_path)
    if set(chans) - {"vv", "vh"}:
        raise ValueError("scene prediction supports SAR-only models; terrain needs the DEM")
    with rasterio.open(scene) as src:
        names = [d.lower() if d else "" for d in src.descriptions]
        bands = {n: src.read(i + 1).astype("float32") for i, n in enumerate(names)}
        profile = src.profile
    valid = np.isfinite(bands["vv"]) & np.isfinite(bands["vh"])
    x = np.stack([scale_db(np.nan_to_num(bands[c], nan=-40.0), c) for c in chans])
    water = predict_array(model, x) & valid
    perm = bands.get("jrc_perm_water")
    flooded = water & ~(np.nan_to_num(perm) > 0) if perm is not None else water
    profile.update(count=2, dtype="uint8", nodata=255, compress="deflate")
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(np.where(valid, flooded, 255).astype("uint8"), 1)
        dst.write(np.where(valid, water, 255).astype("uint8"), 2)
        dst.set_band_description(1, "flooded")
        dst.set_band_description(2, "water")
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("model", type=Path)
    p.add_argument("scene", type=Path)
    p.add_argument("out", type=Path)
    a = p.parse_args(argv)
    print(predict_geotiff(a.model, a.scene, a.out))


if __name__ == "__main__":
    main()
