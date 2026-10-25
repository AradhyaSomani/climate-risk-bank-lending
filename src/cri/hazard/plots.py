"""Quick-look maps used to check hazard tables by eye (Phase 1E/1F).

    python -m cri.hazard.plots cyclone IMD-2019-002 --out docs/figures/cyclone_fani_2019.png
    python -m cri.hazard.plots flood GFD-4309 --out docs/figures/flood_gfd_4309.png
    python -m cri.hazard.plots indicators all --out docs/figures/hazard_indicators.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from cri import config  # noqa: E402
from cri.geo.districts import load_districts  # noqa: E402
from cri.ingest.imd_tracks import load_tracks  # noqa: E402


def _frame(ax, gdf, pad=1.0):
    minx, miny, maxx, maxy = gdf.total_bounds
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.set_aspect("equal")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")


def cyclone_map(event_id: str, out: Path) -> Path:
    d = load_districts()
    c = pd.read_parquet(config.path("processed") / "cyclone_exposure_district_event.parquet")
    c = c[c.event_id == event_id]
    g = d.merge(c, on="district_id")
    fig, ax = plt.subplots(figsize=(7, 7))
    d.plot(ax=ax, color="#eeeeee", edgecolor="white", linewidth=0.2)
    near = g[g.track_dist_km <= 300]
    near.plot(ax=ax, column="track_dist_km", cmap="viridis", legend=True,
              legend_kwds={"label": "distance to track (km)", "shrink": 0.6}, linewidth=0)
    g[g.within_radius].boundary.plot(ax=ax, color="red", linewidth=0.8)
    t = load_tracks()
    t = t[t.storm_id == event_id.removeprefix("IMD-")]
    ax.plot(t.lon, t.lat, "k.-", linewidth=1, markersize=3)
    _frame(ax, near if len(near) else g)
    ver = config.load("project").get("data_version", "dev")
    ax.set_title(f"{event_id}: districts within radius outlined in red (data {ver})", fontsize=9)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out


def flood_map(event_id: str, out: Path) -> Path:
    d = load_districts()
    f = pd.read_parquet(config.path("processed") / "flood_extent_district_event.parquet")
    g = d.merge(f[f.event_id == event_id], on="district_id")
    fig, ax = plt.subplots(figsize=(7, 7))
    d.plot(ax=ax, color="#eeeeee", edgecolor="white", linewidth=0.2)
    g.plot(ax=ax, column="flooded_share", cmap="Blues", legend=True,
           legend_kwds={"label": "flooded share of district", "shrink": 0.6}, linewidth=0)
    _frame(ax, g[g.flooded_share > 0] if (g.flooded_share > 0).any() else g)
    ver = config.load("project").get("data_version", "dev")
    ax.set_title(f"{event_id}: flooded share by district (data {ver})", fontsize=9)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out


def indicators_map(out: Path, columns: list[str] | None = None) -> Path:
    """One small map per Phase 2A indicator, coloured by within-India percentile rank so
    skewed indicators stay readable."""
    from cri.hazard.indicators import CYCLONE, FLOOD, TERRAIN

    d = load_districts()
    ind = pd.read_parquet(config.path("processed") / "hazard_indicators.parquet")
    cols = [c for c in (columns or FLOOD + CYCLONE + TERRAIN) if c in ind.columns]
    g = d.merge(ind, on="district_id", how="left")
    ncol = 4
    nrow = -(-len(cols) // ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 4.4 * nrow))
    for ax, c in zip(axes.ravel(), cols, strict=False):
        # low relative elevation and slope mean more flood-prone, so invert those colours
        cmap = "viridis" if c in ("rel_elev_median_m", "slope_mean_deg") else "viridis_r"
        g.assign(_r=g[c].rank(pct=True)).plot(ax=ax, column="_r", cmap=cmap, linewidth=0,
                                               missing_kwds={"color": "#dddddd"})
        ax.set_title(c, fontsize=9)
        ax.set_axis_off()
    for ax in axes.ravel()[len(cols):]:
        ax.set_axis_off()
    ver = config.load("project").get("data_version", "dev")
    fig.suptitle(f"Phase 2A hazard indicators, percentile rank (dark = more hazard; data {ver})",
                 fontsize=11)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=90, bbox_inches="tight")
    plt.close(fig)
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("kind", choices=["cyclone", "flood", "indicators"])
    p.add_argument("event_id", help="event id, or 'all' for the indicator maps")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    if a.kind == "indicators":
        print(indicators_map(a.out))
        return
    fn = cyclone_map if a.kind == "cyclone" else flood_map
    print(fn(a.event_id, a.out))


if __name__ == "__main__":
    main()
