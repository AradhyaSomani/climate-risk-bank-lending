"""Phase 2B: composite district hazard scores, three versions kept side by side.

- `rank_avg`: mean of the within-India percentile ranks of the indicators.
- `weighted`: weighted mean of the same percentile ranks, weights from configs/hazard.yaml.
- `pca`: first principal component of the standardized indicators (winsorised at the 1st
  and 99th percentiles so one extreme district cannot set the axis), signed to agree with
  `rank_avg`.

Each version is built for flood and for cyclone from the indicators listed under
`score.weights` in the config. The combined score is the larger of the two hazard scores
after each is turned into a percentile, and the combined tier is the higher of the two tiers,
so a district very high on either hazard is very high combined. Tiers come from fixed
percentile cut-offs (`score.tier_cutoffs`). Districts tied at the bottom (for example the
many inland districts no storm has come near) share the lowest percentile, so tier shares are
not exactly 50/25/15/10.

    python -m cri.hazard.score
"""

from __future__ import annotations

import argparse
import logging
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config, contracts

log = logging.getLogger(__name__)

OUT_NAME = "hazard_scores.parquet"
REPORT = Path("docs/eval_reports/hazard_score_stability.md")
VERSIONS = ["rank_avg", "weighted", "pca"]
HAZARDS = ["flood", "cyclone"]


def pct_rank(s: pd.Series) -> pd.Series:
    """Percentile in [0, 1]; ties take the lowest position, so a block of zeros sits at 0."""
    r = s.rank(method="min")
    n = s.notna().sum()
    return (r - 1) / (n - 1) if n > 1 else r * 0.0


def oriented(ind: pd.DataFrame, cols: list[str], direction: dict[str, int]) -> pd.DataFrame:
    return pd.DataFrame({c: ind[c] * direction.get(c, 1) for c in cols}, index=ind.index)


def score_rank_avg(x: pd.DataFrame) -> pd.Series:
    return x.apply(pct_rank).mean(axis=1, skipna=True)


def score_weighted(x: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    r = x.apply(pct_rank)
    w = pd.Series(weights, dtype=float).reindex(r.columns)
    # districts missing an indicator are scored on the others, with the weights renormalised
    num = (r * w).sum(axis=1, skipna=True)
    den = r.notna().mul(w).sum(axis=1)
    return num / den.replace(0, np.nan)


def score_pca(x: pd.DataFrame, reference: pd.Series | None = None
              ) -> tuple[pd.Series, pd.Series, float]:
    """First principal component; returns (score, loadings, share of variance explained)."""
    z = x.clip(x.quantile(0.01), x.quantile(0.99), axis=1)
    z = (z - z.mean()) / z.std(ddof=0).replace(0, np.nan)
    z = z.dropna(axis=1, how="all").fillna(0.0)
    _, s, vt = np.linalg.svd(z.to_numpy(), full_matrices=False)
    load = pd.Series(vt[0], index=z.columns)
    pc = pd.Series(z.to_numpy() @ vt[0], index=x.index)
    ref = reference if reference is not None else score_rank_avg(x)
    if pc.corr(ref, method="spearman") < 0:
        pc, load = -pc, -load
    return pc, load, float(s[0] ** 2 / (s**2).sum())


def tiers(score: pd.Series, cutoffs: list[float]) -> pd.Series:
    """1 = low ... 4 = very high from the score's percentile."""
    p = pct_rank(score)
    return pd.Series(np.searchsorted(np.asarray(cutoffs), p.to_numpy(), side="right") + 1,
                     index=score.index).astype(int)


def compute(ind: pd.DataFrame, cfg: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Long table (district_id, score_version, hazard_type, score, tier) plus PCA details."""
    cfg = cfg or config.load("hazard")["score"]
    ind = ind.set_index("district_id")
    cut = cfg["tier_cutoffs"]
    rows, info = [], {}
    for version in VERSIONS:
        per = {}
        for hz in HAZARDS:
            weights = cfg["weights"][hz]
            cols = [c for c in weights if c in ind.columns]
            if not cols:
                continue
            x = oriented(ind, cols, cfg.get("direction", {}))
            if version == "rank_avg":
                s = score_rank_avg(x)
            elif version == "weighted":
                s = score_weighted(x, {c: weights[c] for c in cols})
            else:
                s, load, expl = score_pca(x)
                info[hz] = {"loadings": load, "explained": expl}
            per[hz] = (s, tiers(s, cut))
            rows.append(pd.DataFrame({"district_id": s.index, "score_version": version,
                                      "hazard_type": hz, "score": s.to_numpy(),
                                      "tier": per[hz][1].to_numpy()}))
        if len(per) == 2:
            (fs, ft), (cs, ct) = per["flood"], per["cyclone"]
            rows.append(pd.DataFrame({
                "district_id": fs.index, "score_version": version, "hazard_type": "combined",
                "score": np.fmax(pct_rank(fs), pct_rank(cs)).to_numpy(),
                "tier": np.maximum(ft, ct).to_numpy(),
            }))
    out = pd.concat(rows, ignore_index=True)
    return out, info


def stability(scores: pd.DataFrame) -> pd.DataFrame:
    """Share of districts with the same tier across versions, per hazard type."""
    wide = scores.pivot_table(index=["hazard_type", "district_id"], columns="score_version",
                              values="tier")
    out = []
    for hz, g in wide.groupby(level="hazard_type"):
        vs = [v for v in VERSIONS if v in g]
        row = {"hazard_type": hz, "districts": len(g)}
        for a, b in combinations(vs, 2):
            row[f"{a}={b}"] = float((g[a] == g[b]).mean())
        row["all_three"] = float(g[vs].nunique(axis=1).eq(1).mean())
        row["within_one_tier"] = float((g[vs].max(axis=1) - g[vs].min(axis=1)).le(1).mean())
        out.append(row)
    return pd.DataFrame(out)


def tier_counts(scores: pd.DataFrame) -> pd.DataFrame:
    return (scores.groupby(["hazard_type", "score_version", "tier"]).size()
            .unstack("tier", fill_value=0).reset_index())


def _md(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + " --- |" * len(cols)]
    for r in df.itertuples(index=False):
        lines.append("| " + " | ".join(floatfmt.format(v) if isinstance(v, float) else str(v)
                                       for v in r) + " |")
    return "\n".join(lines)


def write_report(scores: pd.DataFrame, info: dict, out: Path) -> Path:
    from cri.geo.districts import load_districts

    d = load_districts()[["district_id", "name", "state"]]
    cfg = config.load("hazard")["score"]
    parts = [
        "# Hazard score: versions, tiers and stability (Phase 2B)\n",
        "Generated by `python -m cri.hazard.score`. Weights and tier cut-offs are the "
        f"placeholders in `configs/hazard.yaml` (cut-offs {cfg['tier_cutoffs']}).\n",
        "## Stability of tiers across the three versions\n",
        "Share of districts given the same tier.\n",
        _md(stability(scores)), "",
        "## Districts per tier\n", _md(tier_counts(scores)), "",
    ]
    sus = scores[scores.score_version == "susceptibility"]
    if len(sus):
        ra = scores[(scores.score_version == "rank_avg") & (scores.hazard_type == "flood")]
        m = ra.merge(sus, on="district_id", suffixes=("_rank_avg", "_sus"))
        rho = m.score_rank_avg.corr(m.score_sus, method="spearman")
        parts += ["## Susceptibility version (Phase 2B-C), flood only\n",
                  "Added because the model passed its gate (`docs/model_cards/susceptibility.md`). "
                  f"Against the rank_avg flood score over {len(m)} districts: Spearman "
                  f"{rho:.2f}, same tier {(m.tier_rank_avg == m.tier_sus).mean():.0%}, within "
                  f"one tier {((m.tier_rank_avg - m.tier_sus).abs() <= 1).mean():.0%}. It uses "
                  "terrain and land cover only, so it can flag districts the short flood "
                  "record misses; it is not in the combined score.\n"]
        far = m[(m.tier_sus - m.tier_rank_avg) >= 2].merge(d, on="district_id")
        if len(far):
            parts += ["Districts at least two tiers higher on susceptibility than on the record "
                      f"({len(far)}):\n",
                      _md(far.nlargest(15, "score_sus")[["name", "state", "tier_rank_avg",
                                                         "tier_sus"]]), ""]
    for hz, v in info.items():
        load = v["loadings"].round(2).rename("loading").reset_index()
        load.columns = ["indicator", "loading"]
        parts += [f"## PCA loadings, {hz} (first component explains {v['explained']:.0%})\n",
                  _md(load), ""]
    top = scores[(scores.score_version == "rank_avg")].merge(d, on="district_id")
    for hz in ["flood", "cyclone", "combined"]:
        t = top[top.hazard_type == hz].nlargest(15, "score")[["name", "state", "score", "tier"]]
        parts += [f"## Top 15 districts, {hz} (rank_avg)\n", _md(t), ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts))
    return out


def susceptibility_rows(processed: Path, cutoffs: list[float]) -> pd.DataFrame | None:
    """Flood rows of version `susceptibility` (Phase 2B-C), only if the model's latest run
    passed its gate; None otherwise. The three main versions are left as they are."""
    path = processed / "susceptibility_district.parquet"
    runs = config.path("ml.model_runs")
    if not (path.exists() and runs.exists()):
        return None
    r = pd.read_parquet(runs)
    r = r[r.component == "susceptibility"].sort_values("created_at")
    if r.empty or not bool(r.passed_gate.iloc[-1]):
        log.info("susceptibility model has not passed its gate: version left out")
        return None
    s = pd.read_parquet(path).dropna(subset=["susceptibility"]).set_index("district_id")
    score = pct_rank(s.susceptibility)
    return pd.DataFrame({"district_id": s.index.astype(int), "score_version": "susceptibility",
                         "hazard_type": "flood", "score": score.to_numpy(),
                         "tier": tiers(s.susceptibility, cutoffs).to_numpy()})


def build(report: Path | None = REPORT) -> list[Path]:
    processed = config.path("processed")
    ind = pd.read_parquet(processed / "hazard_indicators.parquet")
    scores, info = compute(ind)
    extra = susceptibility_rows(processed, config.load("hazard")["score"]["tier_cutoffs"])
    if extra is not None:
        scores = pd.concat([scores, extra], ignore_index=True)
    scores["data_version"] = config.load("project").get("data_version", "dev")
    spec = contracts.get_table("C3", "hazard_scores")
    errs = contracts.validate_frame(scores, spec)
    if errs:
        raise ValueError("hazard scores fail contract C3:\n" + "\n".join(errs))
    path = processed / OUT_NAME
    scores.to_parquet(path, index=False)
    log.info("wrote %s (%d rows)", path, len(scores))
    outputs = [path]
    if report is not None:
        outputs.append(write_report(scores, info, report))
    return outputs


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--report", type=Path, default=REPORT)
    a = p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("hazard:score", ["project", "paths", "hazard"]) as outputs:
        outputs += build(a.report)


if __name__ == "__main__":
    main()
