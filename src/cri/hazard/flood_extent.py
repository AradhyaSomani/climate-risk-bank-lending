"""Phase 1E: flooded area per district per event.

    python -m cri.hazard.flood_extent            # every India GFD event -> processed table
    python -m cri.hazard.flood_extent --ids 4309 3365
    python -m cri.hazard.flood_extent --s1       # Sentinel-1 exports in data/raw/sentinel1

Pre-2019 events come from the Global Flood Database. Sentinel-1 extents (Kerala 2018 and
post-2018 events) are exported from Earth Engine by cri.ingest.sentinel1 as rasters with the
same band names, then pass through the same zonal statistics with source s1_otsu or s1_unet:

- `<event_id>_s1_otsu*.tif`: the change-detection map, source s1_otsu;
- `<event_id>_s1_backscatter*.tif`: VV and VH, mapped by the U-Net in `sentinel1.unet_model`
  (configs/hazard.yaml), source s1_unet.

Earth Engine splits a large export into several files (`...-0000000000-0000000000.tif`);
they are mosaicked first. Which source becomes an event's footprint is decided in
cri.events.catalogue.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.stats import spearmanr

from cri import config, contracts
from cri.geo.districts import load_districts
from cri.hazard.zonal_stats import event_flood_extent
from cri.ingest.gfd import fetch_event

log = logging.getLogger(__name__)

OUT_NAME = "flood_extent_district_event.parquet"
# Band order of each Sentinel-1 export, used when a file carries no band names
S1_BANDS = {"otsu": ["flooded", "jrc_perm_water"],
            "backscatter": ["VV", "VH", "jrc_perm_water"],
            "unet": ["flooded", "water"]}
S1_FILE = re.compile(r"(?P<event>.+)_s1_(?P<kind>otsu|backscatter)(-\d+-\d+)?\.tif$")


def gfd_event_id(dfo_id: int) -> str:
    return f"GFD-{int(dfo_id)}"


def build_gfd(ids: list[int] | None = None, keep_rasters: bool | None = None) -> list[Path]:
    """Zonal statistics for every India GFD event; per-event results are cached in interim."""
    hz = config.load("hazard")["flood"]
    keep = hz.get("keep_rasters", True) if keep_rasters is None else keep_rasters
    index = pd.read_csv(config.path("events") / "gfd_india_events.csv")
    if ids:
        index = index[index.dfo_id.isin(ids)]
    districts = load_districts()
    raw_dir = config.path("raw_layers.gfd")
    cache = config.path("interim") / "flood_extent"
    cache.mkdir(parents=True, exist_ok=True)

    parts = []
    for i, ev in enumerate(index.itertuples(), 1):
        eid = gfd_event_id(ev.dfo_id)
        part = cache / f"{eid}.parquet"
        if not part.exists():
            log.info("[%d/%d] %s", i, len(index), eid)
            tif = fetch_event(int(ev.dfo_id), raw_dir, index)
            rows = event_flood_extent(tif, districts, eid, "gfd", hz.get("landcover", True))
            rows.to_parquet(part, index=False)
            # coarse grid of the same event for the susceptibility model (Phase 2B-C)
            from cri.hazard.flood_grid import save_event

            save_event(eid, tif)
            if not keep:
                shutil.rmtree(tif.parent)
        parts.append(pd.read_parquet(part))
    return [write_table(pd.concat(parts, ignore_index=True))]


def s1_exports(raw_dir: Path) -> dict[tuple[str, str], list[Path]]:
    """(event_id, kind) -> the export's GeoTIFF parts in raw_dir."""
    out: dict[tuple[str, str], list[Path]] = {}
    for f in sorted(raw_dir.glob("*_s1_*.tif")) if raw_dir.exists() else []:
        m = S1_FILE.match(f.name)
        if m:
            out.setdefault((m["event"], m["kind"]), []).append(f)
    return out


def _fresh(out: Path, inputs: list[Path]) -> bool:
    return out.exists() and out.stat().st_mtime >= max(p.stat().st_mtime for p in inputs)


def prepare_s1(parts: list[Path], kind: str, out: Path) -> Path:
    """One float32 GeoTIFF from the export's parts: NaN where no scene was seen, and the
    band names zonal statistics and the U-Net look for."""
    from rasterio.merge import merge

    from cri.ingest.sentinel1 import NODATA

    if _fresh(out, parts):
        return out
    srcs = [rasterio.open(p) for p in parts]
    try:
        nodata = srcs[0].nodata if srcs[0].nodata is not None else NODATA.get(kind, 255)
        arr, transform = merge(srcs, nodata=nodata)
        crs, names = srcs[0].crs, list(srcs[0].descriptions)
    finally:
        for src in srcs:
            src.close()
    arr = arr.astype("float32")
    arr[arr == nodata] = np.nan
    expected = S1_BANDS[kind]
    if len(names) != len(expected) or not all(names):
        names = expected
    profile = dict(driver="GTiff", dtype="float32", nodata=np.nan, count=arr.shape[0],
                   height=arr.shape[1], width=arr.shape[2], transform=transform, crs=crs,
                   compress="deflate", tiled=True, blockxsize=256, blockysize=256,
                   BIGTIFF="IF_SAFER")
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(arr)
        for i, n in enumerate(names, 1):
            dst.set_band_description(i, n)
    return out


def build_s1(raw_dir: Path | None = None) -> list[Path]:
    """District rows for every Sentinel-1 export in data/raw/sentinel1 (none: no change)."""
    hz = config.load("hazard")
    exports = s1_exports(raw_dir or config.path("raw_layers.sentinel1"))
    if not exports:
        log.info("no Sentinel-1 exports in data/raw/sentinel1")
        return []
    districts = load_districts()
    work = config.path("interim") / "sentinel1"
    landcover = hz["flood"].get("landcover", True)
    parts = []
    for (eid, kind), files in sorted(exports.items()):
        scene = prepare_s1(files, kind, work / f"{eid}_s1_{kind}.tif")
        if kind == "otsu":
            parts.append(event_flood_extent(scene, districts, eid, "s1_otsu", landcover))
            continue
        model = config.REPO_ROOT / hz["sentinel1"]["unet_model"]
        if not model.exists():
            log.warning("%s: U-Net weights %s missing (dvc pull); backscatter skipped",
                        eid, model)
            continue
        pred = work / f"{eid}_s1_unet_raw.tif"
        if not _fresh(pred, [scene, model]):
            try:
                from cri.ml.flood_cnn.predict import predict_geotiff
            except ImportError as e:  # torch is in the ml extra
                log.warning('%s: %s (pip install -e ".[ml]"); backscatter skipped', eid, e)
                continue
            log.info("%s: running the U-Net on %s", eid, scene.name)
            predict_geotiff(model, scene, pred)
        unet = prepare_s1([pred], "unet", work / f"{eid}_s1_unet.tif")
        parts.append(event_flood_extent(unet, districts, eid, "s1_unet", landcover))
    parts = [p for p in parts if len(p)]
    return [write_table(pd.concat(parts, ignore_index=True))] if parts else []


def write_table(df: pd.DataFrame, name: str = OUT_NAME) -> Path:
    """Validate against contract C3 and write to data/processed (merging other sources)."""
    out = config.path("processed") / name
    if out.exists():
        old = pd.read_parquet(out)
        keys = set(zip(df.event_id, df.source, strict=True))
        old = old[[k not in keys for k in zip(old.event_id, old.source, strict=True)]]
        df = pd.concat([old, df], ignore_index=True)
    df = df.sort_values(["event_id", "source", "district_id"]).reset_index(drop=True)
    spec = contracts.get_table("C3", "flood_extent_district_event")
    errs = contracts.validate_frame(df[list(spec.columns)], spec)
    if errs:
        raise ValueError("flood extent fails contract C3:\n" + "\n".join(errs))
    out.parent.mkdir(parents=True, exist_ok=True)
    df[list(spec.columns)].to_parquet(out, index=False)
    log.info("wrote %s (%d rows, %d events)", out, len(df), df.event_id.nunique())
    return out


def compare_sources(a: pd.DataFrame, b: pd.DataFrame, hit_share: float | None = None) -> dict:
    """Agreement between two extents of the same event (e.g. GFD and Sentinel-1).

    Returns the Spearman correlation of flooded share across districts both cover, the IoU
    of the sets of districts counted as hit, and the mean absolute difference in share.
    """
    if hit_share is None:
        hit_share = config.load("hazard")["flood"]["event_hit_share"]
    m = a[["district_id", "flooded_share"]].merge(
        b[["district_id", "flooded_share"]], on="district_id", suffixes=("_a", "_b")
    )
    if m.empty:
        return {"n_districts": 0}
    hit_a = set(m.district_id[m.flooded_share_a > hit_share])
    hit_b = set(m.district_id[m.flooded_share_b > hit_share])
    union = hit_a | hit_b
    rho = spearmanr(m.flooded_share_a, m.flooded_share_b).statistic if len(m) > 2 else np.nan
    return {
        "n_districts": len(m),
        "spearman": float(rho),
        "hit_iou": len(hit_a & hit_b) / len(union) if union else np.nan,
        "hit_only_a": sorted(hit_a - hit_b),
        "hit_only_b": sorted(hit_b - hit_a),
        "mean_abs_diff": float((m.flooded_share_a - m.flooded_share_b).abs().mean()),
    }


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--ids", type=int, nargs="*", help="GFD DFO ids (default: all India events)")
    p.add_argument("--drop-rasters", action="store_true", help="delete each raster after use")
    p.add_argument("--s1", action="store_true", help="the Sentinel-1 exports instead of GFD")
    a = p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("hazard:flood_extent", ["project", "paths", "hazard"]) as outputs:
        if a.s1:
            outputs += build_s1()
        else:
            outputs += build_gfd(a.ids, keep_rasters=False if a.drop_rasters else None)


if __name__ == "__main__":
    main()
