"""Phase 4B: scenario footprints, i.e. which districts each stress scenario hits and how hard.

Person A builds the footprints; B's stress engine applies the Phase 3 effects to them. Four
kinds, all listed in configs/scenarios.yaml:

- replay: a past event's treated districts and intensities, as in the event catalogue.
- shifted: the same footprint moved to another region. The new footprint is grown from the
  target state's most hazardous district along the district graph, always adding the most
  hazardous neighbour, until it has as many districts as the source. Intensities are
  assigned by hazard rank (the source's worst district goes to the target's most hazardous
  one). Labelled hypothetical.
- scaled: a replay with intensities multiplied by a factor (flooded share capped at 1). Any
  district pushed past the largest intensity in the catalogue is flagged
  `beyond_observed`; B must not extrapolate the effect there without widening the interval.
- compound: two footprints in the same year; a district hit by both keeps the harder hit.
  Whether effects add up is B's call from the Phase 3 evidence.

Intensity is the flooded share for floods and the wind at closest approach (kt) for
cyclones.

    python -m cri.stress.scenarios
"""

from __future__ import annotations

import argparse
import heapq
import logging
from pathlib import Path

import pandas as pd

from cri import config, contracts

log = logging.getLogger(__name__)


def intensity_col(hazard_type: str) -> str:
    return "flooded_share" if hazard_type == "flood" else "max_wind_kt"


def footprint(event_id: str, events: pd.DataFrame, ed: pd.DataFrame) -> pd.DataFrame:
    hz = events.set_index("event_id").hazard_type[event_id]
    f = ed[(ed.event_id == event_id) & ed.treated]
    return pd.DataFrame({"district_id": f.district_id.astype(int),
                         "intensity": f[intensity_col(hz)].astype(float),
                         "heavily_treated": f.heavily_treated.astype(bool)})


def grow_region(seed: int, k: int, adjacency: dict[int, set[int]], score: pd.Series,
                allowed: set[int] | None = None) -> list[int]:
    """k districts grown from `seed`, always adding the highest-scoring neighbour."""
    region, seen = [seed], {seed}
    frontier: list[tuple[float, int]] = []

    def push(d):
        for n in adjacency.get(d, ()):
            if n not in seen and (allowed is None or n in allowed):
                seen.add(n)
                heapq.heappush(frontier, (-float(score.get(n, 0.0)), n))

    push(seed)
    while len(region) < k and frontier:
        _, d = heapq.heappop(frontier)
        region.append(d)
        push(d)
    return region


def shift(src: pd.DataFrame, target_state: str, districts: pd.DataFrame,
          adjacency: dict[int, set[int]], score: pd.Series) -> pd.DataFrame:
    in_state = districts.district_id[districts.state == target_state]
    if in_state.empty:
        raise ValueError(f"unknown state {target_state!r}")
    seed = int(score.reindex(in_state).idxmax())
    region = grow_region(seed, len(src), adjacency, score)
    region = sorted(region, key=lambda d: -score.get(d, 0.0))
    s = src.sort_values("intensity", ascending=False).reset_index(drop=True)
    s = s.iloc[: len(region)]
    return pd.DataFrame({"district_id": region[: len(s)], "intensity": s.intensity.to_numpy(),
                         "heavily_treated": s.heavily_treated.to_numpy()})


def scale(src: pd.DataFrame, factor: float, hazard_type: str, observed_max: float
          ) -> pd.DataFrame:
    out = src.copy()
    out["intensity"] = out.intensity * factor
    if hazard_type == "flood":
        out["intensity"] = out.intensity.clip(upper=1.0)
    out["beyond_observed"] = out.intensity > observed_max
    return out


def compound(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Union of two footprints. A district hit by both keeps one record: the heavily treated
    one if only one is, otherwise the larger intensity (intensities of two different hazards
    are not comparable, so a mixed pair is decided by the heavy-treatment flag first)."""
    both = pd.concat([a, b], ignore_index=True)
    both = both.sort_values(["heavily_treated", "intensity"], ascending=False)
    return both.drop_duplicates("district_id").sort_values("district_id").reset_index(drop=True)


def adjacency_from_edges(edges: pd.DataFrame) -> dict[int, set[int]]:
    adj: dict[int, set[int]] = {}
    for a, b in zip(edges.a, edges.b, strict=True):
        adj.setdefault(int(a), set()).add(int(b))
        adj.setdefault(int(b), set()).add(int(a))
    return adj


def build(processed: Path | None = None) -> list[Path]:
    from cri.geo.districts import load_districts

    cfg = config.load("scenarios")
    processed = processed or config.path("processed")
    events = pd.read_parquet(processed / "events.parquet")
    ed = pd.read_parquet(processed / "event_district.parquet")
    scores = pd.read_parquet(processed / "hazard_scores.parquet")
    adjacency = adjacency_from_edges(pd.read_parquet(processed / "district_edges.parquet"))
    districts = load_districts()[["district_id", "state"]]
    htype = events.set_index("event_id").hazard_type
    obs_max = {hz: float(ed[ed.treated & ed.event_id.isin(htype.index[htype == hz])]
                         [intensity_col(hz)].max()) for hz in ("flood", "cyclone")}

    def hz_score(hz):
        s = scores[(scores.score_version == "rank_avg") & (scores.hazard_type == hz)]
        return s.set_index("district_id").score

    rows, parts = [], []

    def add(sid, stype, source, hz, fp, severity, hypothetical, description, assumptions):
        if fp.empty:
            rows.append({"scenario_id": sid, "scenario_type": stype, "source_event": source,
                         "hazard_type": hz, "severity": severity, "hypothetical": hypothetical,
                         "n_districts": 0, "description": description,
                         "assumptions": assumptions + " No footprint yet: not usable."})
            return
        fp = fp.copy()
        if "beyond_observed" not in fp:
            fp["beyond_observed"] = False
        fp.insert(0, "scenario_id", sid)
        parts.append(fp[["scenario_id", "district_id", "intensity", "heavily_treated",
                         "beyond_observed"]])
        rows.append({"scenario_id": sid, "scenario_type": stype, "source_event": source,
                     "hazard_type": hz, "severity": severity, "hypothetical": hypothetical,
                     "n_districts": len(fp), "description": description,
                     "assumptions": assumptions})

    for ev in cfg["replay"]:
        hz = htype[ev]
        add(f"replay-{ev}", "replay", ev, hz, footprint(ev, events, ed), 1.0, False,
            f"{ev} re-applied to today's lending map",
            "Treated districts and intensities as in the event catalogue.")
    for s in cfg["shifted"]:
        ev, st = s["source"], s["target_state"]
        hz = htype[ev]
        fp = shift(footprint(ev, events, ed), st, districts, adjacency, hz_score(hz))
        add(f"shifted-{ev}-to-{st.replace(' ', '_')}", "shifted", ev, hz, fp, 1.0, True,
            f"{ev} footprint moved to {st}",
            "Grown from the most hazardous district of the target state along shared borders; "
            "intensities matched by hazard rank. Hypothetical.")
    for ev in cfg["scaled"]["sources"]:
        hz = htype[ev]
        for f in cfg["scaled"]["factors"]:
            fp = scale(footprint(ev, events, ed), f, hz, obs_max[hz])
            add(f"scaled-{ev}-x{f:g}", "scaled", ev, hz, fp, float(f), True,
                f"{ev} with intensity x{f:g}",
                f"Same districts; intensity times {f:g} (flood share capped at 1). "
                "beyond_observed marks districts above the largest catalogue intensity.")
    for a, b in cfg["compound"]:
        fp = compound(footprint(a, events, ed), footprint(b, events, ed))
        add(f"compound-{a}+{b}", "compound", a, f"{htype[a]}+{htype[b]}", fp, 1.0, True,
            f"{a} and {b} in the same year",
            "Union of the two footprints; overlapping districts keep the harder hit. "
            "Additivity of effects is decided in Phase 4 from the Phase 3 evidence.")

    scen = pd.DataFrame(rows)
    sd = pd.concat(parts, ignore_index=True)
    out = []
    for name, df in (("scenarios", scen), ("scenario_district", sd)):
        spec = contracts.get_table("C4", name)
        df = df[list(spec.columns)]
        errs = contracts.validate_frame(df, spec)
        if errs:
            raise ValueError(f"{name} fails contract C4:\n" + "\n".join(errs))
        path = processed / f"{name}.parquet"
        df.to_parquet(path, index=False)
        out.append(path)
    log.info("wrote %s and %s\n%s", *out,
             scen[["scenario_id", "n_districts", "hypothetical"]].to_string(index=False))
    return out


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.parse_args(argv)
    runlog.setup_logging()
    with runlog.run("stress:scenarios", ["project", "paths", "scenarios"]) as outputs:
        outputs += build()


if __name__ == "__main__":
    main()
