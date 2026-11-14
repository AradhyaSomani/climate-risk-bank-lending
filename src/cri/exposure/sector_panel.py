"""Annual credit by sector on Census 2011 districts (Phase 1 C, the sector split).

Reads the annual district-by-occupation table (cri.ingest.rbi_annual), maps its labels to
Census 2011 districts with the same rules as the quarterly crosswalk (cri.geo.crosswalk,
configs/crosswalk.yaml) plus the annual-only additions in configs/rbi_annual.yaml
(`crosswalk`), and writes one row per (district, March, sector):

- `data/processed/panel_credit_sector.parquet`: the C2 panel's columns, with `measure =
  credit`, `bank_group = all`, sectors agriculture, industry, services, personal, other and
  all, and `basis = utilisation` (credit where it is used; the quarterly panel is by place of
  sanction). Every Census 2011 district and every year, a missing figure as a null amount.
- `data/processed/crosswalk_annual_to_c2011.parquet`, and its review list in data/interim.

Sectors: agriculture (I), industry (II), services (III transport operators, IV professional
and other services, VI trade, VII finance), personal loans (V), other (VIII all others).
`all` is the district total, which is kept where the split itself is unusable (see
data/interim/rbi_annual_review.csv).

    python -m cri.exposure.sector_panel
"""

from __future__ import annotations

import argparse
import copy
import logging
from pathlib import Path

import pandas as pd

from cri import config
from cri.exposure.panel import apply_crosswalk, check_labels_used, data_version
from cri.geo.crosswalk import build_crosswalk
from cri.ingest.rbi_annual import SECTORS, interim_path

log = logging.getLogger(__name__)

PANEL_FILE = "panel_credit_sector.parquet"
XW_FILE = "crosswalk_annual_to_c2011.parquet"
REVIEW_FILE = "crosswalk_annual_review.csv"
SECTOR_ORDER = ["agriculture", "industry", "services", "personal", "other", "all"]
COLUMNS = ["district_id", "quarter_end", "bank_group", "measure", "sector", "basis",
           "amount_cr", "series_break", "split_flag", "imputed_share", "data_version"]


def merged_config(base: dict, extra: dict) -> dict:
    """configs/crosswalk.yaml with the annual additions merged in, state by state."""
    out = copy.deepcopy(base)
    for section, states in (extra or {}).items():
        sec = out.setdefault(section, {}) or {}
        out[section] = sec
        for state, entries in (states or {}).items():
            if isinstance(entries, list):
                sec[state] = list(sec.get(state) or []) + list(entries)
            else:
                sec[state] = {**(sec.get(state) or {}), **entries}
    return out


def to_sectors(occ: pd.DataFrame) -> pd.DataFrame:
    """Occupation rows to sector rows, in the long form apply_crosswalk takes."""
    o = occ.copy()
    o["sector"] = o.occupation.map(SECTORS).where(o.occupation != "total", "all")
    o = o[o.sector.notna()]
    g = o.groupby(["quarter_end", "rbi_state", "rbi_district", "sector"], as_index=False) \
        .amount_cr.sum(min_count=1)
    return g.assign(bank_group="all", measure="credit", n_offices=float("nan"))


def build_sector_panel(occ: pd.DataFrame, xw: pd.DataFrame, master: pd.DataFrame
                       ) -> pd.DataFrame:
    long = to_sectors(occ)
    check_labels_used(long, xw)
    agg = apply_crosswalk(long, xw)
    grid = pd.MultiIndex.from_product(
        [sorted(master.district_id), sorted(long.quarter_end.unique()), ["all"], ["credit"],
         SECTOR_ORDER],
        names=["district_id", "quarter_end", "bank_group", "measure", "sector"]).to_frame(
        index=False)
    panel = grid.merge(agg.drop(columns="n_offices"), how="left", on=list(grid.columns))
    panel["imputed_share"] = panel.imputed_share.fillna(0.0)
    panel["basis"] = "utilisation"
    panel["series_break"] = False
    panel = panel.merge(master[["district_id", "split_flag"]], on="district_id", how="left")
    panel["data_version"] = data_version()
    panel["district_id"] = panel.district_id.astype(int)
    return panel[COLUMNS].sort_values(["district_id", "quarter_end", "sector"]) \
        .reset_index(drop=True)


def build(out: Path | None = None) -> list[Path]:
    processed = config.path("processed")
    out = out or processed / PANEL_FILE
    occ = pd.read_parquet(interim_path())
    master = pd.read_parquet(config.path("district_geometry.preferred"),
                             columns=["district_id", "name", "state", "population",
                                      "split_flag"])
    cfg = merged_config(config.load("crosswalk"), config.load("rbi_annual").get("crosswalk"))
    totals = occ[occ.occupation == "total"].assign(n_offices=float("nan"), measure="credit")
    xw = build_crosswalk(totals, master, cfg, config.load("district_aliases"),
                         review_path=config.path("interim") / REVIEW_FILE)
    xw_path = processed / XW_FILE
    xw.to_parquet(xw_path, index=False)
    panel = build_sector_panel(occ, xw, master)
    panel.to_parquet(out, index=False)
    has = panel[panel.amount_cr.notna()]
    log.info("sector panel: %d rows, %d with a figure, %d years; written to %s", len(panel),
             len(has), panel.quarter_end.nunique(), out)
    return [out, xw_path]


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for p in build():
        print(p)


if __name__ == "__main__":
    main()
