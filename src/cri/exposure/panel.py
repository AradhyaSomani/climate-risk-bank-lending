"""Quarterly credit and deposit panel on Census 2011 districts (Phase 1 C, contract C2).

Reads RBI's quarterly district statement in long form (cri.ingest.rbi_bsr.build), applies the
C1 crosswalk weights and writes one row per (district, quarter, bank group, measure, sector)
for every Census 2011 district and every quarter in the data, so a missing figure is a row
with a null amount, never a missing row.

- Amount: sum over the RBI labels that map to the district in that quarter, each times its
  weight, in rupees crore (nominal). Null when no label that maps there carries a figure.
- n_offices: the same weighted sum of offices, rounded.
- imputed_share: the part of the amount that came through a weight below 1 (labels shared by
  population, see cri.geo.crosswalk).
- series_break: True for the first quarter of each new reporting regime listed in
  configs/panel.yaml, i.e. the quarters whose change from the previous available quarter
  crosses a break. The regimes are documented in docs/data_cards/rbi.md.

Only `bank_group = all` and `sector = all` exist: RBI's district tables have no bank-group
split and no quarterly sector split (docs/00_rbi_audit.md).

The module computes and writes the table and a coverage report. It does not print or plot any
district's figures: the pre-registration (docs/00_hypotheses.md) is not signed yet.

    python -m cri.exposure.panel
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config

log = logging.getLogger(__name__)

PANEL_FILE = "panel_credit_deposit.parquet"
COLUMNS = ["district_id", "quarter_end", "bank_group", "measure", "sector", "amount_cr",
           "n_offices", "series_break", "split_flag", "imputed_share", "data_version"]


def data_version() -> str:
    ver = str(config.load("project").get("data_version", "dev"))
    return ver if ver.startswith("data-v") else f"data-v0-{ver}"


def _inside(m: pd.DataFrame) -> pd.Series:
    """Rows whose quarter lies in the crosswalk interval (an empty valid_to is open)."""
    return (m.quarter_end >= m.valid_from) & (m.valid_to.isna() | (m.quarter_end <= m.valid_to))


def apply_crosswalk(rbi: pd.DataFrame, xw: pd.DataFrame) -> pd.DataFrame:
    """RBI long rows (one per label, quarter, measure) to weighted rows per 2011 district."""
    m = rbi.merge(xw, left_on=["rbi_state", "rbi_district"], right_on=["rbi_state", "rbi_name"],
                  how="inner")
    m = m[_inside(m)].copy()
    m["amount_w"] = m.amount_cr * m.weight
    m["imputed_w"] = np.where(m.weight < 1, m.amount_w, 0.0)
    m["offices_w"] = m.n_offices * m.weight
    keys = ["district_id", "quarter_end", "bank_group", "measure", "sector"]
    g = m.groupby(keys)
    out = pd.DataFrame({
        "amount_cr": g.amount_w.sum(min_count=1),
        "imputed": g.imputed_w.sum(min_count=1),
        "n_offices": g.offices_w.sum(min_count=1),
    }).reset_index()
    out["imputed_share"] = (out.imputed / out.amount_cr).where(out.amount_cr > 0, 0.0)
    out["imputed_share"] = out.imputed_share.fillna(0.0).clip(0, 1)
    return out.drop(columns="imputed")


def check_labels_used(rbi: pd.DataFrame, xw: pd.DataFrame) -> None:
    """Every RBI row with a figure must fall inside one crosswalk interval."""
    has = rbi[rbi.amount_cr.notna()]
    m = has.merge(xw, left_on=["rbi_state", "rbi_district"],
                  right_on=["rbi_state", "rbi_name"], how="left")
    inside = _inside(m)
    covered = m[inside].groupby(["rbi_state", "rbi_district", "quarter_end", "measure"]).size()
    lost = len(has) - len(covered)
    if lost:
        raise ValueError(f"{lost} RBI rows with a figure fall outside every crosswalk interval")


def build_panel(rbi: pd.DataFrame, xw: pd.DataFrame, master: pd.DataFrame,
                breaks: list) -> pd.DataFrame:
    check_labels_used(rbi, xw)
    agg = apply_crosswalk(rbi, xw)
    quarters = sorted(rbi.quarter_end.unique())
    grid = pd.MultiIndex.from_product(
        [sorted(master.district_id), quarters, ["all"], ["credit", "deposits"], ["all"]],
        names=["district_id", "quarter_end", "bank_group", "measure", "sector"]).to_frame(
        index=False)
    panel = grid.merge(agg, how="left", on=list(grid.columns))
    panel["imputed_share"] = panel.imputed_share.fillna(0.0)
    panel["n_offices"] = panel.n_offices.round().astype("Int64")
    break_dates = {pd.Timestamp(b["quarter_end"]) for b in breaks}
    panel["series_break"] = panel.quarter_end.isin(break_dates)
    panel = panel.merge(master[["district_id", "split_flag"]], on="district_id", how="left")
    panel["data_version"] = data_version()
    panel["district_id"] = panel.district_id.astype(int)
    return panel[COLUMNS].sort_values(["district_id", "quarter_end", "measure"]) \
        .reset_index(drop=True)


def office_jumps(panel: pd.DataFrame, ratio: float = 1.5) -> pd.DataFrame:
    """District-quarters where the office count jumps by more than `ratio` either way from
    the previous reported quarter, outside break quarters.

    Offices are not an outcome, and the crosswalk should leave them smooth: a jump points to
    a label mapped to the wrong district, a label counted twice, or a missed split.
    """
    o = panel[(panel.measure == "deposits") & panel.n_offices.notna()][
        ["district_id", "quarter_end", "n_offices", "series_break"]].copy()
    o = o.sort_values(["district_id", "quarter_end"])
    o["prev"] = o.groupby("district_id").n_offices.shift()
    o["prev_q"] = o.groupby("district_id").quarter_end.shift()
    r = (o.n_offices / o.prev).astype(float)
    jump = ((r > ratio) | (r < 1 / ratio)) & ~o.series_break & (o.prev >= 10)
    return o[jump].assign(ratio=r[jump])


def balance_report(panel: pd.DataFrame, master: pd.DataFrame, breaks: list,
                   jumps: pd.DataFrame) -> str:
    """Coverage only: share of district-quarters with a figure, by state and period."""
    p = panel.merge(master[["district_id", "state"]], on="district_id")
    p["period"] = pd.cut(p.quarter_end, bins=[pd.Timestamp("2000-01-01")] +
                         [pd.Timestamp(b["quarter_end"]) - pd.Timedelta(days=1) for b in breaks] +
                         [pd.Timestamp("2100-01-01")],
                         labels=[b for b in _period_labels(breaks)])
    lines = ["# Panel balance report (Phase 1 J)", "",
             "Generated by `python -m cri.exposure.panel` from "
             "`data/processed/panel_credit_deposit.parquet`. Coverage only: no district's "
             "figures are shown, because the pre-registration is not signed yet.", ""]
    quarters = sorted(p.quarter_end.unique())
    lines += [f"- Districts: {p.district_id.nunique()} (Census 2011). Quarters: {len(quarters)}, "
              f"from {pd.Timestamp(quarters[0]).date()} to {pd.Timestamp(quarters[-1]).date()}.",
              f"- Rows: {len(panel):,}; with a figure: {int(panel.amount_cr.notna().sum()):,} "
              f"({panel.amount_cr.notna().mean():.1%}).",
              f"- Rows with any amount shared by population (imputed_share > 0): "
              f"{int((panel.imputed_share > 0).sum()):,}, in "
              f"{panel.loc[panel.imputed_share > 0, 'district_id'].nunique()} districts.",
              f"- Districts with split_flag: {int(master.split_flag.sum())}.", ""]
    lines += ["## Share of district-quarters with a credit figure, by state and period", ""]
    cred = p[p.measure == "credit"]
    tab = cred.groupby(["state", "period"], observed=True).amount_cr.apply(
        lambda s: s.notna().mean()).unstack()
    lines.append("| State | " + " | ".join(map(str, tab.columns)) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in tab.columns) + " |")
    for state, row in tab.iterrows():
        lines.append(f"| {state} | " + " | ".join(f"{v:.0%}" for v in row) + " |")
    never = cred.groupby(["district_id", "state"]).amount_cr.apply(lambda s: s.notna().sum())
    never = never[never == 0].reset_index()
    names = master.set_index("district_id").name
    lines += ["", "## Districts with no credit figure in any quarter", ""]
    lines += [f"- {names[r.district_id]} ({r.state})" for r in never.itertuples()] or ["- none"]
    lines += ["", "## Office-count jumps (crosswalk check)", "",
              "District-quarters where reporting offices change by more than half from the "
              "previous reported quarter, outside break quarters and for districts with at "
              "least 10 offices. Offices are not an outcome; a jump would point to a label "
              "mapped to the wrong district or counted twice.", ""]
    if jumps.empty:
        lines.append("- none")
    for r in jumps.itertuples():
        lines.append(f"- {names[r.district_id]}: {pd.Timestamp(r.prev_q).date()} to "
                     f"{pd.Timestamp(r.quarter_end).date()}, offices {int(r.prev)} to "
                     f"{int(r.n_offices)}")
    lines += ["", "## Series breaks flagged", ""]
    lines += [f"- {b['quarter_end']}: {b['reason']}" for b in breaks]
    return "\n".join(lines) + "\n"


def _period_labels(breaks: list) -> list[str]:
    starts = ["start"] + [str(b["quarter_end"]) for b in breaks]
    ends = [str(b["quarter_end"]) for b in breaks] + ["end"]
    return [f"{a} to before {b}" if b != "end" else f"{a} onwards"
            for a, b in zip(starts, ends, strict=True)]


def build(out: Path | None = None) -> list[Path]:
    from cri.geo.crosswalk import XW_FILE
    from cri.ingest.rbi_bsr import interim_path

    processed = config.path("processed")
    out = out or processed / PANEL_FILE
    cfg = config.load("panel")
    rbi = pd.read_parquet(interim_path())
    xw = pd.read_parquet(processed / XW_FILE)
    master = pd.read_parquet(config.path("district_geometry.preferred"),
                             columns=["district_id", "name", "state", "split_flag"])
    panel = build_panel(rbi, xw, master, cfg["series_breaks"])
    panel.to_parquet(out, index=False)
    jumps = office_jumps(panel, cfg.get("office_jump_ratio", 1.5))
    report = config.REPO_ROOT / cfg["balance_report"]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(balance_report(panel, master, cfg["series_breaks"], jumps))
    log.info("panel: %d rows, %d with a figure, %d office jumps; written to %s",
             len(panel), int(panel.amount_cr.notna().sum()), len(jumps), out)
    return [out, report]


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    for p in build():
        print(p)


if __name__ == "__main__":
    main()
