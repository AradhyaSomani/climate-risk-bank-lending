"""Phase 4C: a small, honest stochastic event generator.

Historical footprints (GFD floods, IMD cyclones) are grouped by hazard region
(configs/scenarios.yaml). Each simulated year draws a Poisson number of events per region at
the historical rate; each event resamples a historical footprint from its region and moves
it to a random seed district inside the region along the district graph (as the Phase 4B
shifted scenarios do), with intensities matched by hazard rank. Seeds are drawn in
proportion to each district's historical hits plus a small smoothing share.

Event size (flooded area for floods, number of treated districts for cyclones) is resampled
from the record. A generalized Pareto tail is fitted only when there are enough
exceedances; otherwise the generator says so and sizes beyond the record are not modelled.
The output is events and footprints only. Lending change comes from B's stress engine,
which applies the Phase 3 effects to these footprints.

    python -m cri.stress.event_generator     # plus docs/eval_reports/event_generator_check.md
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from cri import config
from cri.hazard.baseline import GFD_FIRST, GFD_LAST
from cri.ingest.imd_tracks import grade_rank
from cri.stress.scenarios import adjacency_from_edges, grow_region

log = logging.getLogger(__name__)

OUT_NAME = "generated_events.parquet"
REPORT = Path("docs/eval_reports/event_generator_check.md")


def historical_footprints(flood: pd.DataFrame, cyclone: pd.DataFrame,
                          district_state: pd.Series, regions: dict, rules: dict
                          ) -> pd.DataFrame:
    """One row per (event, treated district) with region, intensity and event size."""
    fr, cr = rules["flood"], rules["cyclone"]
    f = flood[(flood.source == "gfd") & (flood.flooded_share > fr["treated_share"])]
    f = f.assign(hazard_type="flood", intensity=f.flooded_share, weight=f.flooded_km2)
    c = cyclone[(cyclone.track_dist_km <= cr["treated_km"])
                & (cyclone.grade_closest.map(grade_rank) >= grade_rank(cr["treated_grade"]))]
    c = c.assign(hazard_type="cyclone", intensity=c.wind_kt_closest, weight=1.0)
    rows = pd.concat([f, c], ignore_index=True)[
        ["event_id", "district_id", "hazard_type", "intensity", "weight"]]
    rows["state"] = rows.district_id.map(district_state)
    state_region = {(hz, s): r for hz, rr in regions.items() for r, ss in rr.items() for s in ss}
    rows["region_d"] = [state_region.get((h, s)) for h, s in zip(rows.hazard_type, rows.state,
                                                                  strict=True)]
    # an event belongs to the region holding most of its weight (area or districts)
    w = rows.dropna(subset=["region_d"]).groupby(["event_id", "region_d"]).weight.sum()
    main = w.reset_index().sort_values("weight").drop_duplicates("event_id", keep="last")
    rows = rows.merge(main[["event_id", "region_d"]].rename(columns={"region_d": "region"}),
                      on="event_id")
    size = rows.groupby("event_id").weight.sum().rename("size")
    rows = rows.merge(size, on="event_id")
    return rows.drop(columns=["weight", "region_d"])


def record_years(hazard_type: str, storms: pd.DataFrame | None) -> float:
    if hazard_type == "flood":
        return (GFD_LAST - GFD_FIRST).days / 365.25
    t0 = pd.Timestamp(storms.start_time.min()).tz_localize(None)
    t1 = pd.Timestamp(storms.end_time.max()).tz_localize(None)
    return (t1 - t0).days / 365.25


def fit_tail(sizes: np.ndarray, q: float, min_exceed: int) -> dict:
    """Generalized Pareto above the q-quantile if there are enough exceedances."""
    u = float(np.quantile(sizes, q))
    exc = sizes[sizes > u] - u
    if len(exc) < min_exceed:
        return {"fitted": False, "threshold": u, "n_exceed": int(len(exc))}
    shape, _, scale = stats.genpareto.fit(exc, floc=0)
    return {"fitted": True, "threshold": u, "n_exceed": int(len(exc)), "shape": float(shape),
            "scale": float(scale)}


def simulate(hist: pd.DataFrame, rates: pd.DataFrame, adjacency: dict[int, set[int]],
             score: dict[str, pd.Series], region_districts: dict, tails: dict, years: int,
             seed: int, seed_smoothing: float = 0.1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    by_event = {e: g for e, g in hist.groupby("event_id")}
    events_in = hist.drop_duplicates("event_id").groupby(["hazard_type", "region"]).event_id
    events_in = {k: v.to_numpy() for k, v in events_in}
    parts, n = [], 0
    for r in rates.itertuples():
        counts = rng.poisson(r.rate, size=years)
        pool = events_in[(r.hazard_type, r.region)]
        allowed = region_districts[(r.hazard_type, r.region)]
        cand = np.array(sorted(allowed))
        sc = score[r.hazard_type]
        # seeds follow the record: historical hits per district plus a small smoothing share,
        # so a district never hit in the record can still be hit, but rarely
        hits = (hist[hist.hazard_type == r.hazard_type].groupby("district_id").event_id
                .nunique().reindex(cand).fillna(0).to_numpy())
        p = hits + seed_smoothing * max(hits.mean(), 1e-9)
        p = p / p.sum()
        tail = tails.get(r.hazard_type, {"fitted": False})
        for year in np.flatnonzero(counts):
            for _ in range(counts[year]):
                src = by_event[rng.choice(pool)]
                seed_d = int(rng.choice(cand, p=p))
                region = grow_region(seed_d, len(src), adjacency, sc, allowed)
                region = sorted(region, key=lambda d: -sc.get(d, 0.0))
                inten = np.sort(src.intensity.to_numpy())[::-1][: len(region)]
                size = float(src["size"].iloc[0])
                if tail["fitted"] and size > tail["threshold"] and r.hazard_type == "flood":
                    new = tail["threshold"] + stats.genpareto.rvs(
                        tail["shape"], scale=tail["scale"], random_state=rng)
                    inten = np.clip(inten * new / size, 0, 1)
                    size = new
                parts.append(pd.DataFrame({
                    "year": int(year), "sim_event": n, "hazard_type": r.hazard_type,
                    "region": r.region, "source_event": src.event_id.iloc[0],
                    "district_id": region[: len(inten)], "intensity": inten,
                    "event_size": size}))
                n += 1
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def check(hist: pd.DataFrame, sim: pd.DataFrame, rates: pd.DataFrame, years: int,
          rec_years: dict[str, float], n_districts: int) -> dict[str, pd.DataFrame]:
    """Simulated against historical: event rates, sizes and how often each district is hit."""
    ev_sim = sim.drop_duplicates("sim_event")
    counts = ev_sim.groupby(["hazard_type", "region"]).size().rename("sim_events")
    freq = rates.set_index(["hazard_type", "region"]).join(counts).fillna(0)
    freq["sim_rate"] = freq.sim_events / years
    size_rows = []
    for hz, g in hist.drop_duplicates("event_id").groupby("hazard_type"):
        s_sim = ev_sim[ev_sim.hazard_type == hz].event_size.to_numpy()
        s_hist = g["size"].to_numpy()
        ks = stats.ks_2samp(s_hist, s_sim) if len(s_sim) else None
        size_rows.append({"hazard_type": hz, "hist_events": len(s_hist),
                          "hist_median": float(np.median(s_hist)),
                          "sim_median": float(np.median(s_sim)) if len(s_sim) else np.nan,
                          "hist_max": float(s_hist.max()),
                          "sim_p99": float(np.quantile(s_sim, 0.99)) if len(s_sim) else np.nan,
                          "ks_stat": float(ks.statistic) if ks else np.nan})
    hit_rows = []
    for hz in hist.hazard_type.unique():
        h = hist[hist.hazard_type == hz].groupby("district_id").event_id.nunique()
        h = h / rec_years[hz] * 10
        s = sim[sim.hazard_type == hz].groupby("district_id").sim_event.nunique() / years * 10
        both = pd.DataFrame({"h": h, "s": s}).fillna(0)
        hit_rows.append({"hazard_type": hz, "districts_hit_hist": int((both.h > 0).sum()),
                         "sim_share_in_never_hit": float(both.s[both.h == 0].sum()
                                                         / max(both.s.sum(), 1e-12)),
                         "spearman_per_decade": float(stats.spearmanr(both.h, both.s).statistic),
                         "mean_hits_per_decade_hist": float(both.h.sum() / n_districts),
                         "mean_hits_per_decade_sim": float(both.s.sum() / n_districts)})
    return {"rates": freq.reset_index(), "sizes": pd.DataFrame(size_rows),
            "district_hits": pd.DataFrame(hit_rows)}


def build(processed: Path | None = None, report: Path | None = REPORT) -> list[Path]:
    from cri.geo.districts import load_districts
    from cri.hazard.score import _md

    cfg = config.load("scenarios")["generator"]
    rules = config.load("events")
    processed = processed or config.path("processed")
    flood = pd.read_parquet(processed / "flood_extent_district_event.parquet")
    cyclone = pd.read_parquet(processed / "cyclone_exposure_district_event.parquet")
    storms = pd.read_parquet(processed / "cyclone_storms.parquet")
    scores = pd.read_parquet(processed / "hazard_scores.parquet")
    adjacency = adjacency_from_edges(pd.read_parquet(processed / "district_edges.parquet"))
    districts = load_districts()[["district_id", "state"]]
    dstate = districts.set_index("district_id").state

    hist = historical_footprints(flood, cyclone, dstate, cfg["regions"], rules)
    ev_n = hist.groupby("event_id").district_id.nunique()
    hist = hist[hist.event_id.map(ev_n) >= cfg["event_min_districts"]]
    rec = {"flood": record_years("flood", None), "cyclone": record_years("cyclone", storms)}
    rates = (hist.drop_duplicates("event_id").groupby(["hazard_type", "region"]).size()
             .rename("hist_events").reset_index())
    rates["record_years"] = rates.hazard_type.map(rec)
    rates["rate"] = rates.hist_events / rates.record_years
    region_districts = {(hz, r): set(districts.district_id[districts.state.isin(ss)])
                        for hz, rr in cfg["regions"].items() for r, ss in rr.items()}
    score = {hz: scores[(scores.score_version == "rank_avg") & (scores.hazard_type == hz)]
             .set_index("district_id").score for hz in ("flood", "cyclone")}
    sizes = hist.drop_duplicates("event_id")
    tails = {hz: fit_tail(g["size"].to_numpy(), cfg["gpd_threshold_quantile"],
                          cfg["gpd_min_exceedances"]) for hz, g in sizes.groupby("hazard_type")}
    sim = simulate(hist, rates, adjacency, score, region_districts, tails, cfg["years"],
                   cfg["seed"], cfg.get("seed_smoothing", 0.1))
    sim["data_version"] = config.load("project").get("data_version", "dev")
    path = processed / OUT_NAME
    sim.to_parquet(path, index=False)
    out = [path]
    if report is not None:
        chk = check(hist, sim, rates, cfg["years"], rec, len(districts))
        tail_rows = pd.DataFrame([{"hazard_type": k, **v} for k, v in tails.items()])
        text = [
            "# Event generator check (Phase 4C)\n",
            f"Generated by `python -m cri.stress.event_generator`: {cfg['years']:,} simulated "
            f"years, seed {cfg['seed']}. Floods from GFD ({rec['flood']:.1f} years), cyclones "
            f"from the IMD best track ({rec['cyclone']:.1f} years); an event counts if it "
            "treats at least one district under configs/events.yaml. Sizes: flooded km2 for "
            "floods, treated districts for cyclones.\n",
            "## Event rates by region (per year)\n", _md(chk["rates"]), "",
            "## Event sizes\n",
            "The KS statistic compares simulated and historical sizes (0 = identical).\n",
            _md(chk["sizes"]), "",
            "## Heavy tail\n",
            "A generalized Pareto is used only with enough exceedances; otherwise sizes are "
            "resampled from the record and nothing larger than the largest recorded event is "
            "generated.\n",
            _md(tail_rows), "",
            "## How often each district is hit\n",
            "Spearman correlation across districts between simulated and historical hits per "
            "decade, and the share of simulated hits that land in districts the record never "
            "saw hit. Shifting footprints within a region spreads hits beyond the short "
            "record, by design; that share says how far.\n",
            _md(chk["district_hits"]), "",
        ]
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("\n".join(text))
        out.append(report)
    log.info("wrote %s (%d simulated events)", path, sim.sim_event.nunique())
    return out


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--report", type=Path, default=REPORT)
    a = p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("stress:event_generator", ["project", "paths", "scenarios", "events"]) as o:
        o += build(report=a.report)


if __name__ == "__main__":
    main()
