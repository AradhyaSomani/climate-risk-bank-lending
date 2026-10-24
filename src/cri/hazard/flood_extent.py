"""Phase 1E: flooded area per district per event.

    python -m cri.hazard.flood_extent            # every India GFD event -> processed table
    python -m cri.hazard.flood_extent --ids 4309 3365

Pre-2019 events come from the Global Flood Database. Sentinel-1 extents (Kerala 2018 and
post-2018 events) are exported from Earth Engine by cri.ingest.sentinel1 as rasters with the
same band names, then pass through the same zonal statistics with source s1_otsu or s1_unet.
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from cri import config, contracts
from cri.geo.districts import load_districts
from cri.hazard.zonal_stats import event_flood_extent
from cri.ingest.gfd import fetch_event

log = logging.getLogger(__name__)

OUT_NAME = "flood_extent_district_event.parquet"


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
    a = p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("hazard:flood_extent", ["project", "paths", "hazard"]) as outputs:
        outputs += build_gfd(a.ids, keep_rasters=False if a.drop_rasters else None)


if __name__ == "__main__":
    main()
