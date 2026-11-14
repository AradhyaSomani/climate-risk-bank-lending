"""Phase 2 D: where Indian bank lending sits relative to flood and cyclone hazard.

For each quarter, bank group, sector and measure (credit, deposits) in the C2 panel, and
each hazard score version and type in C3 (`hazard_scores.parquet`), this computes:

- `exposure_by_tier.parquet`: the amount and the share of the all-India total in each
  hazard tier (1 low to 4 very high), over the districts that have a figure that quarter,
  with that coverage alongside;
- `exposure_concentration.parquet`: the share in the 10 and 50 most hazardous districts,
  and a Herfindahl index of the amount across districts (how concentrated lending is, with
  or without hazard);
- `exposure_by_state.parquet`: per state, the share of its own amount in the high and very
  high tiers (state is the level at which bank-level disclosures can be matched, 2E);
- `exposure_trend.parquet`: the high-tier share's change per year inside each reporting
  regime (between the series breaks of configs/panel.yaml), and its jump across each break,
  so a trend that is only a break shows up as one.

- `exposure_by_sector.parquet`: the tier table for the annual credit-by-sector panel
  (cri.exposure.sector_panel: each March, by place of utilisation), when it has been built.

The panel's district weights already come from the crosswalk (C1), so a district's amount is
its share of every RBI label it belongs to. The quarterly series is all banks and all
sectors; the sector split comes from the annual tables, which have no bank-group split.

These are levels of credit across all districts, not outcomes around events, but they
include post-event quarters; run it after the pre-registration is signed (`prereg-v1`).

    python -m cri.exposure.district_exposure
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config

log = logging.getLogger(__name__)

KEYS = ["quarter_end", "bank_group", "measure", "sector"]
HAZ = ["score_version", "hazard_type"]
OUTPUTS = {"tier": "exposure_by_tier.parquet", "concentration": "exposure_concentration.parquet",
           "state": "exposure_by_state.parquet", "trend": "exposure_trend.parquet",
           "sector": "exposure_by_sector.parquet"}


def _amounts(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel[panel.amount_cr.notna()]
    return p[KEYS + ["district_id", "amount_cr", "series_break"]]


def by_tier(panel: pd.DataFrame, scores: pd.DataFrame, n_districts: int) -> pd.DataFrame:
    """Amount and share per hazard tier; `coverage` is the share of districts with a figure."""
    p = _amounts(panel)
    m = p.merge(scores[HAZ + ["district_id", "tier"]], on="district_id")
    g = m.groupby(KEYS + HAZ + ["tier"], observed=True).agg(
        amount_cr=("amount_cr", "sum"), districts=("district_id", "nunique")).reset_index()
    tot = g.groupby(KEYS + HAZ).amount_cr.transform("sum")
    g["share"] = g.amount_cr / tot
    cov = p.groupby(KEYS).district_id.nunique().rename("coverage") / n_districts
    brk = p.groupby(KEYS).series_break.any()
    return g.join(cov, on=KEYS).join(brk, on=KEYS)


def concentration(panel: pd.DataFrame, scores: pd.DataFrame, top: list[int]) -> pd.DataFrame:
    """Share of the amount in the `top` most hazardous districts (by score, among districts
    with a figure that quarter), and the Herfindahl index across districts."""
    p = _amounts(panel)
    rows = []
    for (sv, hz), s in scores.groupby(HAZ):
        rank = s.set_index("district_id").score.rank(ascending=False, method="first")
        m = p.assign(rank=p.district_id.map(rank))
        for key, g in m.groupby(KEYS):
            tot = g.amount_cr.sum()
            if tot <= 0:
                continue
            order = g.sort_values("rank").amount_cr.to_numpy()
            sh = g.amount_cr.to_numpy() / tot
            rows.append({**dict(zip(KEYS, key, strict=True)), "score_version": sv,
                         "hazard_type": hz, "hhi": float((sh ** 2).sum()),
                         **{f"top{n}_share": float(order[:n].sum() / tot) for n in top}})
    return pd.DataFrame(rows)


def by_state(panel: pd.DataFrame, scores: pd.DataFrame, master: pd.DataFrame,
             high: list[int]) -> pd.DataFrame:
    p = _amounts(panel).merge(master[["district_id", "state"]], on="district_id")
    m = p.merge(scores[HAZ + ["district_id", "tier"]], on="district_id")
    m["high_amount"] = m.amount_cr.where(m.tier.isin(high), 0.0)
    g = m.groupby(KEYS + HAZ + ["state"])[["amount_cr", "high_amount"]].sum().reset_index()
    g["high_share"] = g.high_amount / g.amount_cr.where(g.amount_cr > 0)
    return g.drop(columns="high_amount")


def trend(tier: pd.DataFrame, breaks: list[pd.Timestamp], high: list[int]) -> pd.DataFrame:
    """Per series: slope of the high-tier share (percentage points per year) inside each
    regime, and the jump across each break (first quarter of the new regime minus the last
    published quarter before it)."""
    hi = tier[tier.tier.isin(high)].groupby(KEYS + HAZ).share.sum().reset_index()
    edges = [pd.Timestamp.min, *sorted(breaks), pd.Timestamp.max]
    rows = []
    for key, g in hi.groupby(["bank_group", "measure", "sector"] + HAZ):
        g = g.sort_values("quarter_end")
        base = dict(zip(["bank_group", "measure", "sector"] + HAZ, key, strict=True))
        for lo, nxt in zip(edges[:-1], edges[1:], strict=True):
            seg = g[(g.quarter_end >= lo) & (g.quarter_end < nxt)]
            if len(seg) < 2:
                continue
            t = (seg.quarter_end - seg.quarter_end.iloc[0]).dt.days / 365.25
            slope = np.polyfit(t, 100 * seg.share, 1)[0]
            rows.append({**base, "kind": "regime", "start": seg.quarter_end.iloc[0],
                         "end": seg.quarter_end.iloc[-1], "pp": float(slope)})
        for b in breaks:
            before, after = g[g.quarter_end < b], g[g.quarter_end >= b]
            if before.empty or after.empty:
                continue
            rows.append({**base, "kind": "break", "start": before.quarter_end.iloc[-1],
                         "end": after.quarter_end.iloc[0],
                         "pp": float(100 * (after.share.iloc[0] - before.share.iloc[-1]))})
    return pd.DataFrame(rows)


def reader_table(tier: pd.DataFrame, version: str, high: list[int]) -> pd.DataFrame:
    """For the latest quarter and each bank group and sector: the share of credit in the
    high and very high tiers, per hazard type (the table section D asks for)."""
    t = tier[(tier.score_version == version) & (tier.measure == "credit")]
    last = t.quarter_end.max()
    t = t[t.quarter_end == last]
    out = t.assign(level=np.where(t.tier == max(high), "very_high",
                                  np.where(t.tier.isin(high), "high", "other")))
    out = out[out.level != "other"].pivot_table(
        index=["bank_group", "sector", "hazard_type"], columns="level", values="share",
        aggfunc="sum", fill_value=0.0).reset_index()
    out.columns.name = None
    out["quarter_end"] = last
    return out


def build(out_dir: Path | None = None) -> list[Path]:
    cfg = config.load("exposure")
    proc = config.path("processed")
    out_dir = out_dir or proc
    panel = pd.read_parquet(proc / "panel_credit_deposit.parquet")
    scores = pd.read_parquet(proc / "hazard_scores.parquet")
    master = pd.read_parquet(config.path("district_geometry.preferred"),
                             columns=["district_id", "state"])
    breaks = [pd.Timestamp(b["quarter_end"]) for b in config.load("panel")["series_breaks"]]
    high = cfg["high_tiers"]
    tier = by_tier(panel, scores, master.district_id.nunique())
    tables = {"tier": tier,
              "concentration": concentration(panel, scores, cfg["top_n"]),
              "state": by_state(panel, scores, master, high),
              "trend": trend(tier, breaks, high)}
    sector_path = proc / "panel_credit_sector.parquet"
    if sector_path.exists():
        sp = pd.read_parquet(sector_path)
        tables["sector"] = by_tier(sp, scores, master.district_id.nunique())
    else:
        log.info("no %s: run python -m cri.exposure.sector_panel for the sector split",
                 sector_path.name)
    written = []
    for k, df in tables.items():
        path = out_dir / OUTPUTS[k]
        df.to_parquet(path, index=False)
        written.append(path)
    log.info("exposure: %d tier rows, %d series; written to %s", len(tier),
             tier.groupby(KEYS + HAZ).ngroups, out_dir)
    return written


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for p in build():
        print(p)


if __name__ == "__main__":
    main()
