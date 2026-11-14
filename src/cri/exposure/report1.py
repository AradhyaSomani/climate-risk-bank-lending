"""Report 1 (Phase 2 G): where Indian bank lending sits relative to flood and cyclone hazard.

Reads the Phase 2 D exposure tables, the panel, the hazard scores and the district master,
and writes `docs/report1_exposure.md` with two figures in `docs/figures/`. Every number in
the text comes from this module, so rerunning it after a data update rewrites the report.

    python -m cri.exposure.report1
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config

log = logging.getLogger(__name__)

REPORT = Path("docs/report1_exposure.md")
FIG_MAP = Path("docs/figures/report1_map.png")
FIG_TREND = Path("docs/figures/report1_trend.png")
HAZARDS = ["flood", "cyclone", "combined"]
VERSIONS = ["rank_avg", "weighted", "pca"]

# reference palette (dataviz skill, light mode): categorical slots 1-3, ordinal blue ramp
SERIES = {"flood": "#2a78d6", "cyclone": "#eb6834", "combined": "#1baf7a"}
TIER_RAMP = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


# ---------------------------------------------------------------------------- numbers

def pct(x: float, nd: int = 0) -> str:
    return "n/a" if pd.isna(x) else f"{100 * x:.{nd}f}%"


def high_share(tier: pd.DataFrame, high: list[int]) -> pd.DataFrame:
    """Share in the high tiers per quarter, measure, version and hazard (all banks)."""
    t = tier[(tier.bank_group == "all") & (tier.sector == "all") & tier.tier.isin(high)]
    return t.groupby(["quarter_end", "measure", "score_version", "hazard_type"]) \
        .share.sum().reset_index()


def snapshot(panel: pd.DataFrame, scores: pd.DataFrame, master: pd.DataFrame,
             quarter: pd.Timestamp, version: str, high: list[int], metro: list[int]
             ) -> pd.DataFrame:
    """For one quarter: share of districts, population, credit and deposits in the high
    tiers, with and without the metro credit centres."""
    p = panel[(panel.quarter_end == quarter) & (panel.bank_group == "all")
              & (panel.sector == "all")]
    amt = p.pivot_table(index="district_id", columns="measure", values="amount_cr")
    rows = []
    for hz in HAZARDS:
        s = scores[(scores.score_version == version) & (scores.hazard_type == hz)]
        d = master[["district_id", "population"]].merge(s[["district_id", "tier"]]) \
            .merge(amt, on="district_id", how="left")
        hi = d.tier.isin(high)
        out = {"hazard_type": hz, "districts": hi.mean(),
               "population": d.population[hi].sum() / d.population.sum()}
        nm = ~d.district_id.isin(metro)
        for m in ["credit", "deposits"]:
            out[m] = d[m][hi].sum() / d[m].sum()
            out[f"{m}_ex_metro"] = d[m][hi & nm].sum() / d[m][nm].sum()
        rows.append(out)
    return pd.DataFrame(rows)


def top_districts(panel: pd.DataFrame, scores: pd.DataFrame, master: pd.DataFrame,
                  quarter: pd.Timestamp, version: str, n: int) -> pd.DataFrame:
    """The districts holding the most credit in the very high combined tier."""
    p = panel[(panel.quarter_end == quarter) & (panel.measure == "credit")
              & (panel.bank_group == "all") & (panel.sector == "all")]
    tot = p.amount_cr.sum()
    s = scores[(scores.score_version == version)].pivot_table(
        index="district_id", columns="hazard_type", values="tier")
    d = p.merge(master[["district_id", "name", "state"]], on="district_id") \
        .join(s, on="district_id")
    d = d[d.combined == 4].sort_values("amount_cr", ascending=False).head(n)
    return d.assign(share=d.amount_cr / tot)[["name", "state", "flood", "cyclone", "share"]]


def states(by_state: pd.DataFrame, quarter: pd.Timestamp, version: str, n: int
           ) -> pd.DataFrame:
    s = by_state[(by_state.quarter_end == quarter) & (by_state.measure == "credit")
                 & (by_state.score_version == version) & (by_state.hazard_type == "combined")
                 & (by_state.bank_group == "all") & (by_state.sector == "all")].copy()
    s["high_amount"] = s.amount_cr * s.high_share
    s["of_india_high"] = s.high_amount / s.high_amount.sum()
    return s.sort_values("high_amount", ascending=False).head(n)


SECTOR_NAMES = {"agriculture": "Agriculture", "industry": "Industry", "services": "Services",
                "personal": "Personal loans", "other": "Other", "all": "All credit"}


def sector_shares(sec: pd.DataFrame, quarter: pd.Timestamp, version: str, high: list[int]
                  ) -> pd.DataFrame:
    """Per sector: its share of all credit, and the share of its credit in the high tiers
    of each hazard (annual tables, place of utilisation)."""
    s = sec[(sec.quarter_end == quarter) & (sec.score_version == version)
            & (sec.bank_group == "all")]
    hi = s[s.tier.isin(high)].groupby(["sector", "hazard_type"]).share.sum().unstack()
    amt = s[s.hazard_type == "combined"].groupby("sector").amount_cr.sum()
    out = hi.join((amt / amt.get("all", np.nan)).rename("of_all"))
    order = [k for k in SECTOR_NAMES if k in out.index]
    return out.loc[order]


# ---------------------------------------------------------------------------- figures

def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def trend_figure(hs: pd.DataFrame, hs_ex: pd.DataFrame, version: str,
                 breaks: list[pd.Timestamp], out: Path) -> None:
    """High-tier share of credit over time, all districts and without the metro centres,
    on one y-scale; unpublished quarters stay as gaps; series breaks dashed."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True, dpi=200)
    fig.patch.set_facecolor(SURFACE)
    cal = pd.date_range(hs.quarter_end.min(), hs.quarter_end.max(), freq="QE")
    for ax, data, title in [(axes[0], hs, "All districts"),
                            (axes[1], hs_ex, "Without the six metro credit centres")]:
        _style(ax)
        d = data[(data.measure == "credit") & (data.score_version == version)]
        for hz in HAZARDS:
            y = d[d.hazard_type == hz].set_index("quarter_end").share.reindex(cal) * 100
            ax.plot(cal, y, color=SERIES[hz], linewidth=2, solid_capstyle="round")
            # quarters published on their own (annual March figures from 2023) as dots
            alone = y.notna() & y.shift(1).isna() & y.shift(-1).isna()
            ax.plot(cal[alone.to_numpy()], y[alone], linestyle="none", marker="o",
                    markersize=4, color=SERIES[hz], markeredgecolor=SURFACE,
                    markeredgewidth=0.8)
            last = y.dropna()
            ax.annotate(hz, (last.index[-1], last.iloc[-1]), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=8, color=INK)
        for b in breaks:
            ax.axvline(b, color=INK2, linewidth=0.8, linestyle=(0, (3, 3)))
        ax.set_title(title, fontsize=9, color=INK, loc="left")
        ax.set_xlim(cal[0], cal[-1] + pd.Timedelta(days=900))
    axes[0].set_ylabel("Share of credit in high and very high tiers (%)", fontsize=8,
                       color=INK2)
    axes[0].set_ylim(0, 70)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def map_figure(geo, scores: pd.DataFrame, panel: pd.DataFrame, quarter: pd.Timestamp,
               version: str, out: Path) -> None:
    """Districts shaded by combined hazard tier, with a circle per district sized by its
    credit (area proportional to the amount)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    s = scores[(scores.score_version == version) & (scores.hazard_type == "combined")]
    g = geo.merge(s[["district_id", "tier"]], on="district_id")
    p = panel[(panel.quarter_end == quarter) & (panel.measure == "credit")
              & (panel.bank_group == "all") & (panel.sector == "all")]
    g = g.merge(p[["district_id", "amount_cr"]], on="district_id", how="left")
    fig, ax = plt.subplots(figsize=(6.5, 7.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for t in range(1, 5):
        g[g.tier == t].plot(ax=ax, color=TIER_RAMP[t - 1], edgecolor=SURFACE, linewidth=0.15)
    pts = g.geometry.representative_point()
    amt = g.amount_cr.fillna(0)
    size = 900 * amt / amt.max()
    ax.scatter(pts.x, pts.y, s=size, facecolor="none", edgecolor=INK, linewidth=0.5)
    ax.set_axis_off()
    labels = ["Low", "Medium", "High", "Very high"]
    handles = [Patch(facecolor=c, edgecolor="none", label=f"{lab} hazard")
               for c, lab in zip(TIER_RAMP, labels, strict=True)]
    ref = [0.01, 0.05]
    tot = amt.sum()
    handles += [Line2D([], [], marker="o", linestyle="none", markerfacecolor="none",
                       markeredgecolor=INK, markersize=np.sqrt(900 * r * tot / amt.max()),
                       label=f"{pct(r)} of India's credit") for r in ref]
    ax.legend(handles=handles, loc="lower left", fontsize=7, frameon=False,
              labelcolor=INK, labelspacing=1.1)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------------------- report

def md_table(df: pd.DataFrame) -> list[str]:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    out += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return out


def sector_bullet(sec: pd.DataFrame | None, version: str, high: list[int]) -> list[str]:
    if sec is None:
        return []
    t = sector_shares(sec, sec.quarter_end.max(), version, high)
    return [f"- **Farm credit is the least exposed to flood.** In the annual"
            f" tables (credit where it is used), {pct(t.loc['agriculture', 'flood'])} of"
            f" agricultural credit is in high flood tiers, against"
            f" {pct(t.loc['all', 'flood'])} of all credit and"
            f" {pct(t.loc['services', 'flood'])} of services (section 3)."]


def sector_section(sec: pd.DataFrame | None, version: str, high: list[int]) -> list[str]:
    if sec is None:
        return []
    q = sec.quarter_end.max()
    t = sector_shares(sec, q, version, high)
    lines = ["", "## 3. Sectors", "",
             f"From RBI's annual tables of credit by district and occupation ({q:%B %Y})."
             " They count credit where it is used, not where it is booked, so head-office"
             " lending sits closer to the borrower than in the quarterly figures above."
             " Services are transport operators, professional services, trade and finance.",
             ""]
    lines += md_table(pd.DataFrame({
        "Sector": [SECTOR_NAMES[k] for k in t.index],
        "Share of all credit": [pct(x) for x in t.of_all],
        **{f"{hz.capitalize()}: share in high tiers": [pct(x) for x in t[hz]]
           for hz in HAZARDS}}))
    f = t.drop(index="all")["flood"]
    lines += ["",
              f"{SECTOR_NAMES[f.idxmin()]} credit is the least exposed to flood"
              f" ({pct(f.min())} in the high tiers, against {pct(t.loc['all', 'flood'])} of all"
              f" credit) and {SECTOR_NAMES[f.idxmax()].lower()} the most ({pct(f.max())})."]
    return lines


def write(root: Path | None = None) -> Path:
    import geopandas as gpd

    root = root or config.REPO_ROOT
    cfg = config.load("exposure")
    high, metro, version = cfg["high_tiers"], cfg["metro_hq"], cfg["report_version"]
    proc = config.path("processed")
    panel = pd.read_parquet(proc / "panel_credit_deposit.parquet")
    scores = pd.read_parquet(proc / "hazard_scores.parquet")
    geo = gpd.read_parquet(config.path("district_geometry.preferred"))
    master = pd.DataFrame(geo.drop(columns="geometry"))
    tier = pd.read_parquet(proc / "exposure_by_tier.parquet")
    conc = pd.read_parquet(proc / "exposure_concentration.parquet")
    by_state = pd.read_parquet(proc / "exposure_by_state.parquet")
    trend = pd.read_parquet(proc / "exposure_trend.parquet")
    sec_path = proc / "exposure_by_sector.parquet"
    sec = pd.read_parquet(sec_path) if sec_path.exists() else None
    breaks = [pd.Timestamp(b["quarter_end"]) for b in config.load("panel")["series_breaks"]]

    first, last = tier.quarter_end.min(), tier.quarter_end.max()
    hs = high_share(tier, high)
    # the same series without the metro centres, from the panel
    from cri.exposure.district_exposure import by_tier

    nm = panel[~panel.district_id.isin(metro)]
    hs_ex = high_share(by_tier(nm, scores, master.district_id.nunique() - len(metro)), high)
    snap = snapshot(panel, scores, master, last, version, high, metro)
    snap0 = snapshot(panel, scores, master, first, version, high, metro)
    rng = hs[(hs.quarter_end == last) & hs.score_version.isin(VERSIONS)] \
        .groupby(["measure", "hazard_type"]).share.agg(["min", "max"])
    sus = hs[(hs.quarter_end == last) & (hs.score_version == "susceptibility")] \
        .set_index("measure").share
    top = top_districts(panel, scores, master, last, version, 10)
    st = states(by_state, last, version, 8)
    tr = trend[(trend.score_version == version) & (trend.bank_group == "all")
               & (trend.sector == "all")]
    c = conc[(conc.score_version == version) & (conc.measure == "credit")
             & (conc.bank_group == "all") & (conc.sector == "all")]

    (root / FIG_MAP.parent).mkdir(parents=True, exist_ok=True)
    map_figure(geo, scores, panel, last, version, root / FIG_MAP)
    trend_figure(hs, hs_ex, version, breaks, root / FIG_TREND)

    S = snap.set_index("hazard_type")
    S0 = snap0.set_index("hazard_type")
    lq, fq = last.strftime("%B %Y"), first.strftime("%B %Y")
    p_last = panel[(panel.quarter_end == last) & (panel.measure == "credit")
                   & (panel.bank_group == "all") & (panel.sector == "all")]
    mumbai = p_last[p_last.district_id.isin(cfg["mumbai"])].amount_cr.sum() \
        / p_last.amount_cr.sum()
    L = [
        "# Where Indian bank lending sits relative to flood and cyclone hazard",
        "",
        f"Report 1 (Phase 2 G). Generated by `python -m cri.exposure.report1` from the panel"
        f" ({fq} to {lq}), the `{version}` hazard scores and the Phase 2 D exposure tables."
        " Shares are of the credit and deposits of all scheduled commercial banks, regional"
        " rural banks included, by the district where the loan is booked.",
        "",
        "## Summary",
        "",
        f"- In {lq}, **{pct(S.loc['combined', 'credit'])} of bank credit** sat in districts"
        " with a high or very high flood or cyclone hazard (the top two tiers of either), which"
        f" are {pct(S.loc['combined', 'districts'])} of districts and hold"
        f" {pct(S.loc['combined', 'population'])} of the population. For flood alone the share"
        f" is {pct(S.loc['flood', 'credit'])}; for cyclone alone"
        f" {pct(S.loc['cyclone', 'credit'])}.",
        f"- **The metro credit centres lift the figures.** Mumbai's two districts book"
        f" {pct(mumbai)} of India's credit, and both are high on flood and on cyclone."
        " Without the six largest credit centres (Mumbai, Delhi, Chennai, Bangalore, Kolkata,"
        " Hyderabad), where head offices book loans used elsewhere, the combined share is"
        f" {pct(S.loc['combined', 'credit_ex_metro'])}, a little below the population share.",
        "- **Outside the metros, flood-prone districts get less credit than their population"
        " and cyclone-prone ones more.** Flood: "
        f"{pct(S.loc['flood', 'credit_ex_metro'])} of credit against"
        f" {pct(S.loc['flood', 'population'])} of people (largely rural districts of the"
        " Ganga and Brahmaputra plains). Cyclone:"
        f" {pct(S.loc['cyclone', 'credit_ex_metro'])} against"
        f" {pct(S.loc['cyclone', 'population'])} (coastal districts from Gujarat round to West"
        " Bengal, including commercial ones such as Thane, Krishna and Visakhapatnam).",
        *sector_bullet(sec, version, high),
        "- **Over twenty years the share has barely moved, but outside the metros it has"
        f" risen.** The combined share was {pct(S0.loc['combined', 'credit'])} in {fq};"
        " without the metros it rose from"
        f" {pct(S0.loc['combined', 'credit_ex_metro'])} to"
        f" {pct(S.loc['combined', 'credit_ex_metro'])}. Inside each reporting regime the"
        " all-district share moves by less than half a percentage point a year, and the 2017"
        " series break moves it by less than a point (deposits by up to two points).",
        f"- **The answer depends on the score version, for flood.** Across the three"
        " composite versions the flood share ranges from"
        f" {pct(rng.loc[('credit', 'flood'), 'min'])} to"
        f" {pct(rng.loc[('credit', 'flood'), 'max'])}; the susceptibility model puts it at"
        f" {pct(sus.get('credit', np.nan))}. Cyclone is the same in every version.",
        "",
        f"![Combined hazard tier by district, with circles sized by credit, {lq}]"
        f"({FIG_MAP.relative_to('docs')})",
        "",
        f"*Figure 1. Combined hazard tier (the higher of the flood and cyclone tiers) and"
        f" credit by district, {lq}. Circle area is proportional to the credit booked in the"
        " district.*",
        "",
        "## 1. How much lending sits in high-hazard districts",
        "",
        f"Shares in tiers 3 and 4 (high and very high), {lq}. Tiers are fixed percentiles of"
        " each district's score within India (`configs/hazard.yaml`): high is the 75th to"
        " 90th percentile, very high the top 10%. The combined tier is the higher of the two,"
        " so more districts are high on it than on either hazard alone.",
        "",
    ]
    t1 = pd.DataFrame({
        "Hazard": [h.capitalize() for h in HAZARDS],
        "Districts": [pct(S.loc[h, "districts"]) for h in HAZARDS],
        "Population (2011)": [pct(S.loc[h, "population"]) for h in HAZARDS],
        "Credit": [pct(S.loc[h, "credit"]) for h in HAZARDS],
        "Deposits": [pct(S.loc[h, "deposits"]) for h in HAZARDS],
        "Credit, without metros": [pct(S.loc[h, "credit_ex_metro"]) for h in HAZARDS],
        "Deposits, without metros": [pct(S.loc[h, "deposits_ex_metro"]) for h in HAZARDS],
    })
    L += md_table(t1)
    L += ["", "The ten districts with the most credit in the very high combined tier:", ""]
    tiers = {1: "low", 2: "medium", 3: "high", 4: "very high"}
    L += md_table(pd.DataFrame({
        "District": top.name, "State": top.state,
        "Flood tier": top.flood.map(tiers), "Cyclone tier": top.cyclone.map(tiers),
        "Share of India's credit": [pct(x, 1) for x in top.share]}))
    L += ["",
          "Mumbai's very high flood tier is partly an artefact: its Census 2011 boundary"
          " reaches into the sea and the harbour, so 51% of its area counts as permanent water"
          " (`docs/data_cards/hazard_tables.md`). Its cyclone tier does not depend on that.",
          "", "## 2. States", "",
          f"The states with the most credit in high or very high combined-hazard districts,"
          f" {lq}:", ""]
    L += md_table(pd.DataFrame({
        "State": st.state,
        "Share of the state's credit in high tiers": [pct(x) for x in st.high_share],
        "Share of India's high-tier credit": [pct(x) for x in st.of_india_high]}))
    L += sector_section(sec, version, high)
    L += ["", "## 4. Over time", "",
          f"![Share of credit in high and very high tiers, {fq} to {lq}]"
          f"({FIG_TREND.relative_to('docs')})", "",
          "*Figure 2. Share of credit in the high and very high tiers by hazard, with and"
          " without the six metro credit centres. Dashed lines are RBI series breaks (June 2017"
          " and March 2023); gaps are quarters RBI did not publish, and from March 2023 the"
          " panel has March figures only, shown as dots.*", "",
          "Change in the high-tier share of credit and of deposits, all districts, in"
          " percentage points: per year inside each reporting regime, and the jump across each"
          " break.", ""]
    rows = []
    for hz in HAZARDS:
        for m in ["credit", "deposits"]:
            x = tr[(tr.hazard_type == hz) & (tr.measure == m)]
            reg = x[x.kind == "regime"].sort_values("start")
            brk = x[x.kind == "break"].sort_values("start")
            rows.append([hz.capitalize(), m] + [f"{v:+.2f}" for v in reg.pp]
                        + [f"{v:+.2f}" for v in brk.pp])
    L += md_table(pd.DataFrame(rows, columns=[
        "Hazard", "Measure", "2004-2016 per year", "2017-2022 per year", "2023-2026 per year",
        "Break 2017", "Break 2023"]))
    L += ["",
          "Inside every regime the change is a fraction of a point a year, so the drift over"
          " twenty years is a few points. The 2017 break (bank credit instead of gross bank"
          " credit, quarter-end dates, 2011 population groups) moves the deposit shares by one"
          " to two points, so a trend read across it would partly be the break. Without the"
          " metro centres the shares rise slowly instead (right panel of Figure 2): credit has"
          " grown faster in hazard-prone districts outside the centres than elsewhere outside"
          " them.",
          "", "## 5. Concentration", "",
          "Share of credit in the most hazardous districts (ranked by score), and the"
          " Herfindahl index of credit across all districts (0 = spread evenly, 1 = all in"
          " one).", ""]
    rows = []
    for hz in HAZARDS:
        for q in [first, last]:
            r = c[(c.hazard_type == hz) & (c.quarter_end == q)].iloc[0]
            rows.append([hz.capitalize(), q.strftime("%b %Y"), pct(r.top10_share, 1),
                         pct(r.top50_share, 1), f"{r.hhi:.3f}"])
    L += md_table(pd.DataFrame(rows, columns=["Hazard", "Quarter", "Top 10 districts",
                                              "Top 50 districts", "Herfindahl (credit)"]))
    L += ["",
          "The most hazardous districts are mostly rural and hold little credit: the ten most"
          " flood-prone hold about 1% of it. Only for cyclone does the top of the ranking reach"
          " big credit centres. Credit as a whole has become less concentrated: the Herfindahl"
          f" index fell from {c[c.quarter_end == first].hhi.iloc[0]:.3f} to"
          f" {c[c.quarter_end == last].hhi.iloc[0]:.3f}.",
          "", "## 6. How much the answer depends on choices", "",
          f"High-tier share of credit in {lq} under each hazard score version"
          " (Phase 2 F will add tier cut-offs, cyclone radius and the crosswalk flags):", ""]
    v = hs[(hs.quarter_end == last) & (hs.measure == "credit")] \
        .pivot_table(index="hazard_type", columns="score_version", values="share")
    names = {"weighted": "Weighted (used here)", "rank_avg": "Rank average", "pca": "PCA",
             "susceptibility": "Susceptibility model"}
    order = [c for c in names if c in v.columns]
    L += md_table(pd.DataFrame({
        "Hazard": [h.capitalize() for h in v.index],
        **{names[col]: [pct(x) for x in v[col]] for col in order}}))
    L += ["", "## What this does not show", "",
          "- **Where loans are used.** RBI's quarterly series books credit where it is"
          " sanctioned, so head-office lending to firms across India sits in Mumbai, Delhi and"
          " the other centres. In March 2007, 154 of 606 districts differed by more than"
          " 1.25 times between credit by sanction and by use (`docs/00_location_basis.md`). The"
          " 'without metros' columns are the closer guide to where lending is exposed.",
          "- **Bank groups.** RBI's district tables have no split by bank group; bank-group"
          " exposure needs the Phase 2 E routes. The sector split (section 3) is annual and"
          " by place of utilisation, so it does not line up exactly with the quarterly"
          " figures by place of sanction.",
          "- **Hazard is relative.** Tiers rank districts within India; they are not"
          " probabilities of loss.",
          "- **Effects.** This is where lending sits, not what happens to it after a flood or"
          " cyclone: that is the event study (Phase 3).", ""]
    out = root / REPORT
    out.write_text("\n".join(L))
    log.info("report 1: %s", out)
    return out


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(write())


if __name__ == "__main__":
    main()
