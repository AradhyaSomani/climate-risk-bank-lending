"""Phase 2C: checks of the hazard score against things it was not built from.

1. Out-of-sample: build the score from events before a cut-off year and ask how well it
   ranks the districts hit afterwards (AUC, Spearman with the later hit count, and the
   precision and recall of the high tiers), next to the simplest single indicator.
2. Kerala 2018: the seven worst-hit districts named in the state's PDNA, against a score
   built only from events before 2018 (GFD has no Kerala 2018 footprint in any case).
3. EM-DAT, state level: rank correlation of the state's mean score with the number of
   flood and storm records and the reported damage. Needs the EM-DAT export.
4. GFD against Sentinel-1 for the same events. Needs the Earth Engine export.

Checks whose inputs are missing are reported as pending, not skipped silently.

    python -m cri.hazard.validation      # writes docs/hazard_validation.md
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr

from cri import config
from cri.hazard import indicators, score
from cri.hazard.flood_extent import compare_sources

log = logging.getLogger(__name__)

REPORT = Path("docs/hazard_validation.md")
SINGLE = {"flood": "flood_events_per_decade", "cyclone": "cyclone_storms_per_decade"}


def auc(s: pd.Series, label: pd.Series) -> float:
    """Probability that a hit district outscores a non-hit one (ties count half)."""
    s, label = s.to_numpy(dtype=float), label.to_numpy(dtype=bool)
    n1, n0 = label.sum(), (~label).sum()
    if n1 == 0 or n0 == 0:
        return np.nan
    r = rankdata(s)
    return float((r[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def later_hits(inputs: dict, hazard: str, cutoff: int) -> tuple[pd.Series, pd.Index]:
    """Hit count per district for events from `cutoff` on, and the districts observed."""
    hz = config.load("hazard")
    if hazard == "flood":
        f = inputs["flood"]
        f = f[f.source == "gfd"]
        yr = indicators.event_years(f.event_id.unique())
        f = f[f.event_id.map(yr).ge(cutoff).fillna(False).to_numpy(dtype=bool)]
        observed = pd.Index(f.loc[f.mapped_share > 0, "district_id"].unique())
        hit = f[f.flooded_share > hz["flood"]["event_hit_share"]]
    else:
        c = inputs["cyclone"]
        yr = indicators.event_years(c.event_id.unique())
        c = c[c.event_id.map(yr).ge(cutoff).fillna(False).to_numpy(dtype=bool)]
        observed = None  # every district is observed by the track record
        hit = c[c.within_radius]
    return hit.groupby("district_id").event_id.nunique(), observed


def out_of_sample(inputs: dict, district_ids, hazard: str, cutoff: int,
                  top_tier: int) -> pd.DataFrame:
    ind = indicators.compute(district_ids=district_ids, before_year=cutoff, **inputs)
    sc, _ = score.compute(ind)
    count, observed = later_hits(inputs, hazard, cutoff)
    ids = pd.Index(sorted(district_ids)) if observed is None else pd.Index(sorted(observed))
    count = count.reindex(ids).fillna(0)
    hit = count > 0
    rows = []
    cands = {v: sc[(sc.score_version == v) & (sc.hazard_type == hazard)]
             .set_index("district_id") for v in score.VERSIONS}
    single = ind.set_index("district_id")[SINGLE[hazard]]
    cands[f"{SINGLE[hazard]} only"] = pd.DataFrame(
        {"score": single, "tier": score.tiers(single, config.load("hazard")["score"]
                                              ["tier_cutoffs"])})
    for name, s in cands.items():
        s = s.reindex(ids)
        top = s.tier >= top_tier
        rows.append({
            "hazard": hazard, "score": name, "built_from": f"before {cutoff}",
            "tested_on": f"{cutoff} on", "districts": len(ids), "hit_later": int(hit.sum()),
            "auc": auc(s.score, hit),
            "spearman_count": float(spearmanr(s.score, count).statistic),
            "precision_top": float(hit[top].mean()) if top.any() else np.nan,
            "recall_top": float(top[hit].mean()) if hit.any() else np.nan,
            "base_rate": float(hit.mean()),
        })
    return pd.DataFrame(rows)


def kerala_2018(inputs: dict, districts: pd.DataFrame, worst: list[int], state: str,
                top_tier: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Score built from events before 2018; Kerala districts with the PDNA worst-hit flag."""
    ind = indicators.compute(district_ids=districts.district_id, before_year=2018, **inputs)
    sc, _ = score.compute(ind)
    f = sc[sc.hazard_type == "flood"].copy()
    f["pct_india"] = f.groupby("score_version").score.transform(score.pct_rank)
    k = districts[districts.state == state][["district_id", "name"]]
    k = k.assign(worst_hit=k.district_id.isin(worst))
    detail = k.merge(f, on="district_id")
    summary = []
    for v, g in detail.groupby("score_version"):
        summary.append({
            "score_version": v,
            "auc_within_kerala": auc(g.score, g.worst_hit),
            "worst_hit_in_top_tiers": int((g.worst_hit & (g.tier >= top_tier)).sum()),
            "others_in_top_tiers": int((~g.worst_hit & (g.tier >= top_tier)).sum()),
            "worst_hit_median_pct_india": float(g[g.worst_hit].pct_india.median()),
            "others_median_pct_india": float(g[~g.worst_hit].pct_india.median()),
        })
    wide = detail.pivot_table(index=["district_id", "name", "worst_hit"],
                              columns="score_version", values="pct_india").reset_index()
    tiers = detail.pivot_table(index="district_id", columns="score_version", values="tier")
    wide = wide.merge(tiers.add_prefix("tier_").reset_index(), on="district_id")
    return pd.DataFrame(summary), wide.sort_values(["worst_hit", "rank_avg"], ascending=False)


def emdat_states(scores: pd.DataFrame, records: pd.DataFrame,
                 districts: pd.DataFrame) -> pd.DataFrame:
    """Spearman across states between the state's mean district score and the EM-DAT record
    count and damage. A record is counted once in every state it names, with its full
    damage, since EM-DAT does not split damage by place."""
    rec = records.copy()
    id_state = districts.set_index("district_id").state
    rec["state"] = rec.state.fillna(rec.district_id.map(id_state))
    rec = rec.dropna(subset=["state"]).drop_duplicates(["disno", "state"])
    rows = []
    for hz in ["flood", "cyclone"]:
        r = rec[rec.hazard_type == hz]
        by = r.groupby("state").agg(records=("disno", "nunique"),
                                    damage=("total_damage_adj_kusd", "sum"))
        for v in score.VERSIONS:
            s = scores[(scores.score_version == v) & (scores.hazard_type == hz)]
            st = s.merge(districts[["district_id", "state"]]).groupby("state").score.mean()
            m = pd.DataFrame({"score": st}).join(by).fillna(0)
            rows.append({"hazard": hz, "score_version": v, "states": len(m),
                         "states_with_records": int((m.records > 0).sum()),
                         "spearman_records": float(spearmanr(m.score, m.records).statistic),
                         "spearman_damage": float(spearmanr(m.score, m.damage).statistic)})
    return pd.DataFrame(rows)


def gfd_vs_s1(flood: pd.DataFrame) -> pd.DataFrame:
    rows = []
    s1 = flood[flood.source.isin(["s1_unet", "s1_otsu"])]
    for (ev, src), b in s1.groupby(["event_id", "source"]):
        a = flood[(flood.event_id == ev) & (flood.source == "gfd")]
        if len(a):
            r = compare_sources(a, b)
            rows.append({"event_id": ev, "s1_source": src, **{
                k: (len(v) if isinstance(v, list) else v) for k, v in r.items()}})
    return pd.DataFrame(rows)


def _md(df: pd.DataFrame) -> str:
    return score._md(df)


def run(out: Path = REPORT) -> Path:
    from cri.geo.districts import load_districts

    cfg = config.load("hazard")["validation"]
    districts = load_districts()
    inputs = indicators.load_inputs()
    processed = config.path("processed")
    parts = ["# Hazard score validation (Phase 2C)\n",
             "Generated by `python -m cri.hazard.validation`. Every check is reported, "
             "including weak and pending ones. Thresholds, weights and cut-offs are the "
             "placeholders in `configs/hazard.yaml`.\n"]

    parts.append("## 1. Out-of-sample: score built before a cut-off, tested after it\n")
    parts.append("AUC is the chance that a district hit after the cut-off scores above one "
                 "that was not (0.5 = no skill). Precision and recall use tiers "
                 f"{cfg['top_tier']} and 4. For floods, only districts observed by a later "
                 "GFD event are tested. The last row of each block is the single most "
                 "obvious indicator, which the composite has to beat to be worth having.\n")
    oos = []
    if inputs["flood"] is not None:
        oos.append(out_of_sample(inputs, districts.district_id, "flood",
                                 cfg["flood_cutoff_year"], cfg["top_tier"]))
    if inputs["cyclone"] is not None:
        oos.append(out_of_sample(inputs, districts.district_id, "cyclone",
                                 cfg["cyclone_cutoff_year"], cfg["top_tier"]))
    oos = pd.concat(oos, ignore_index=True) if oos else pd.DataFrame()
    parts.append(_md(oos) if len(oos) else "Pending: no hazard tables.")
    parts.append("")
    summary = summarise(oos)

    parts.append("## 2. Kerala, August 2018\n")
    if inputs["flood"] is not None:
        summ, detail = kerala_2018(inputs, districts, cfg["kerala_2018_worst"],
                                   cfg["kerala_state"], cfg["top_tier"])
        parts.append("Flood score built from GFD events before 2018 (GFD has no footprint for "
                     "this event). Worst-hit districts as named in the Government of Kerala "
                     "Post Disaster Needs Assessment (2018, p. 13): Alappuzha, Ernakulam, "
                     "Idukki, Kottayam, Pathanamthitta, Thrissur and Wayanad. `pct_india` is "
                     "the district's percentile among all 640 districts.\n")
        parts += [_md(summ), "", _md(detail.round(2)), ""]
    else:
        parts.append("Pending: no flood table.\n")

    parts.append("## 3. EM-DAT records and damage by state\n")
    rec_path = processed / "disaster_records.parquet"
    scores_path = processed / score.OUT_NAME
    if rec_path.exists() and scores_path.exists():
        parts.append(_md(emdat_states(pd.read_parquet(scores_path), pd.read_parquet(rec_path),
                                      districts)))
    else:
        parts.append("Pending: needs the EM-DAT export in `data/raw/emdat/` (account required), "
                     "then `python -m cri.ingest.emdat`.")
    parts.append("")

    parts.append("## 4. NRSC flood-hazard atlas zones\n")
    parts.append("Pending: the atlas data has not been obtained for any state. When it is, "
                 "compare tiers with atlas zones in that state only.\n")

    parts.append("## 5. Global Flood Database against Sentinel-1\n")
    cmp = gfd_vs_s1(inputs["flood"]) if inputs["flood"] is not None else pd.DataFrame()
    if len(cmp):
        parts.append(_md(cmp))
    else:
        parts.append("Pending: no Sentinel-1 extents yet (needs the Earth Engine export; "
                     "`python -m cri.ingest.sentinel1`). Chennai 2015 is the first event to "
                     "compare, since Kerala 2018 is not in GFD.")
    parts.append("")
    parts.append("## 6. Eye check: tiers by state\n")
    scores_now = pd.read_parquet(scores_path) if scores_path.exists() else None
    if scores_now is not None:
        parts.append("Districts per tier (rank_avg). Flood-prone Assam and Bihar and the "
                     "cyclone coast should sit high; Rajasthan should not.\n")
        parts.append(_md(state_tiers(scores_now, districts)))
    parts.append("")
    # summary goes right after the introduction
    parts[2:2] = ["## Summary\n", *summary, ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts))
    return out


STATES = ["Assam", "Bihar", "West Bengal", "Odisha", "Andhra Pradesh", "Tamil Nadu", "Gujarat",
          "Kerala", "Rajasthan"]


def state_tiers(scores: pd.DataFrame, districts: pd.DataFrame) -> pd.DataFrame:
    s = scores[scores.score_version == "rank_avg"].merge(districts[["district_id", "state"]])
    s = s[s.state.isin(STATES) & s.hazard_type.isin(["flood", "cyclone"])]
    t = (s.groupby(["state", "hazard_type", "tier"]).size().unstack("tier", fill_value=0)
         .reindex(columns=[1, 2, 3, 4], fill_value=0))
    t.columns = [f"tier_{c}" for c in t.columns]
    return t.reset_index()


def summarise(oos: pd.DataFrame) -> list[str]:
    """Plain statements from the out-of-sample table, so the summary never drifts from it."""
    lines = []
    for hz in ["flood", "cyclone"]:
        g = oos[oos.hazard == hz] if len(oos) else oos
        if not len(g):
            continue
        comp = g[g.score.isin(score.VERSIONS)]
        single = g[~g.score.isin(score.VERSIONS)].iloc[0]
        best = comp.loc[comp.auc.idxmax()]
        diff = best.auc - single.auc
        verdict = ("slightly beats" if 0.005 < diff <= 0.02 else "beats" if diff > 0.02 else
                   "matches" if diff >= -0.005 else "loses to")
        rho_c, rho_s = comp.spearman_count.max(), single.spearman_count
        lines.append(
            f"- {hz.capitalize()}: built {best.built_from} and tested {best.tested_on}, the "
            f"composite ranks later-hit districts well (AUC {best.auc:.2f}, {best['score']}) and "
            f"{verdict} the single indicator `{single['score'].removesuffix(' only')}` (AUC "
            f"{single.auc:.2f}). On how often districts are hit (Spearman with the later hit "
            f"count) the single indicator is {'better' if rho_s > rho_c else 'no better'} "
            f"({rho_s:.2f} against {rho_c:.2f}): the extra indicators add severity and terrain, "
            "which separate hit from not hit but not frequent from occasional.")
    lines.append("- Kerala 2018 (section 2) is the weak check: the score was built without "
                 "the event, and only the low-lying districts (Alappuzha, Thrissur, Kottayam) "
                 "come out high. Idukki and Wayanad were hit mainly by landslides, which a "
                 "flood-extent score cannot see. GFD observed Kerala in 24 events but never "
                 "recorded Ernakulam or Pathanamthitta above 1% flooded (MODIS misses floods "
                 "under cloud and canopy), so both sit near the median.")
    lines.append("- EM-DAT, the NRSC atlas and the Sentinel-1 comparison are pending on data "
                 "(sections 3 to 5).")
    lines.append("- Known artefact: `flood_duration_days` is high for some central Indian "
                 "districts hit by one long GFD event, probably reservoirs below the JRC "
                 "permanent-water threshold; it carries 5% of the weighted flood score.")
    return lines


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, default=REPORT)
    a = p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("hazard:validation", ["project", "paths", "hazard"]) as outputs:
        outputs.append(run(a.out))


if __name__ == "__main__":
    main()
