"""District-quarter controls (Phase 1 D): `data/processed/controls_district_quarter.parquet`.

One row per Census 2011 district and calendar quarter, from March 2004 to the end of the
study period in configs/project.yaml:

- Census 2011, fixed over time: population, urban share (households), agricultural workers
  (cultivators and agricultural labourers) over all workers, literates over population.
- Rainfall (CHIRPS): the quarter's total in mm (district mean), and its anomaly against the
  mean of the same calendar quarter over the normal period (`rain_normal`).
- Night lights: VIIRS monthly radiance averaged over the quarter's months (from 2014), and
  the harmonised DMSP-VIIRS annual value of the quarter's year (to 2021), the long series
  that bridges the 2013-14 change of satellite (configs/controls.yaml).
- State farm loan waivers: whether one covering commercial-bank loans was announced in the
  quarter in the district's state, one covering cooperative banks only, and the quarters
  since the latest one covering commercial banks.
- Elections: state assembly and Lok Sabha results declared in the quarter, and the quarters
  until the district's next assembly results (credit to farmers rises before elections,
  Cole 2009).
- Large state policy shocks (the Andhra Pradesh microfinance ordinance, the state's
  bifurcation, and others in configs/controls.yaml): a flag in the quarter one began.

Waivers, elections and shocks name a Census 2011 state, or a `region` (a list of districts)
for part of one: Telangana's elections and waiver cover its ten districts only.

Rainfall and night lights come from the Earth Engine tables in data/raw/controls/
(cri.ingest.ee_controls). When they are not there yet the columns stay empty and the rest is
built, so `make data` never depends on Earth Engine.

    python -m cri.exposure.controls
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from cri import config

log = logging.getLogger(__name__)

CONTROLS_FILE = "controls_district_quarter.parquet"
PERIOD_COL = re.compile(r"^p(\d{4})(?:_(\d{2}))?$")


def read_ee_tables(folder: Path, product: str) -> pd.DataFrame:
    """Long table district_id, period (Timestamp of the period start), value from every
    `<product>_batch*.csv` in `folder`; empty if there are none."""
    files = sorted(folder.glob(f"{product}_batch*.csv"))
    if not files:
        return pd.DataFrame(columns=["district_id", "period", "value"])
    wide = pd.concat([pd.read_csv(f).assign(_file=f.name) for f in files], ignore_index=True)
    dup = wide[wide.district_id.duplicated(keep=False)]
    if not dup.empty:
        raise ValueError(
            f"{product}: a district appears in more than one file "
            f"({', '.join(sorted(dup._file.unique()))}). Google Drive names a second export "
            "of the same name '<name> (1).csv'; keep only the newer copy of each batch")
    cols = [c for c in wide.columns if PERIOD_COL.match(c)]
    long = wide.melt(id_vars="district_id", value_vars=cols, var_name="col", value_name="value")
    parts = long.col.str.extract(PERIOD_COL)
    month = parts[1].fillna("01")
    long["period"] = pd.to_datetime(parts[0] + "-" + month + "-01")
    long["district_id"] = long.district_id.astype(int)
    return long[["district_id", "period", "value"]]


def quarter_end(ts: pd.Series) -> pd.Series:
    return ts.dt.to_period("Q").dt.end_time.dt.normalize()


def rain_quarterly(monthly: pd.DataFrame, normal: tuple[int, int]) -> pd.DataFrame:
    """Quarter totals (all three months needed) and the anomaly against the normal."""
    if monthly.empty:
        return pd.DataFrame(columns=["district_id", "quarter_end", "rain_mm", "rain_anom"])
    m = monthly.assign(quarter_end=quarter_end(monthly.period))
    g = m.groupby(["district_id", "quarter_end"]).value
    q = pd.DataFrame({"rain_mm": g.sum(min_count=1), "n": g.count()}).reset_index()
    q.loc[q.n < 3, "rain_mm"] = np.nan
    q["qtr"] = q.quarter_end.dt.quarter
    years = q.quarter_end.dt.year
    base = q[(years >= normal[0]) & (years <= normal[1])]
    norm = base.groupby(["district_id", "qtr"]).rain_mm.mean().rename("rain_normal")
    q = q.join(norm, on=["district_id", "qtr"])
    q["rain_anom"] = np.where(q.rain_normal > 0, q.rain_mm / q.rain_normal - 1, np.nan)
    return q[["district_id", "quarter_end", "rain_mm", "rain_anom"]]


def ntl_quarterly(monthly: pd.DataFrame) -> pd.DataFrame:
    """Quarter mean of the monthly radiance. The stray-light corrected composites hold small
    negative district means where background noise is subtracted from dark land (201 of
    72,000 district-months in the November 2026 export, none below -0.05); they are set to
    0, the usual treatment, before averaging."""
    if monthly.empty:
        return pd.DataFrame(columns=["district_id", "quarter_end", "ntl_viirs"])
    m = monthly.assign(quarter_end=quarter_end(monthly.period),
                       value=monthly.value.clip(lower=0))
    out = m.groupby(["district_id", "quarter_end"]).value.mean().rename("ntl_viirs")
    return out.reset_index()


def ntl_annual(annual: pd.DataFrame) -> pd.DataFrame:
    if annual.empty:
        return pd.DataFrame(columns=["district_id", "year", "ntl_harmonized"])
    return annual.assign(year=annual.period.dt.year).rename(
        columns={"value": "ntl_harmonized"})[["district_id", "year", "ntl_harmonized"]]


def census_controls(census: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    c = pd.DataFrame({
        "district_id": census["District code"].astype(int),
        "ag_worker_share_2011": (census.Cultivator_Workers + census.Agricultural_Workers)
        / census.Workers,
        "literacy_2011": census.Literate / census.Population,
    })
    m = master[["district_id", "population", "urban_share"]].rename(
        columns={"population": "population_2011", "urban_share": "urban_share_2011"})
    return m.merge(c, on="district_id", how="left", validate="one_to_one")


def _grid(master: pd.DataFrame, quarters: list[pd.Timestamp]) -> pd.DataFrame:
    return pd.MultiIndex.from_product([sorted(master.district_id), quarters],
                                      names=["district_id", "quarter_end"]).to_frame(index=False)


def event_districts(entries: list[dict], master: pd.DataFrame, date_key: str,
                    regions: dict | None = None) -> pd.DataFrame:
    """One row per entry and district it covers: entry (its position), district_id and the
    quarter_end of `entry[date_key]`. An entry names a Census 2011 `state` ("ALL" for every
    district) or a `region` from configs/controls.yaml `regions` (a list of districts, for
    a part of a Census 2011 state such as Telangana)."""
    regions = regions or {}
    states = set(master.state)
    ids_by_state = master.groupby("state").district_id.apply(list).to_dict()
    known = set(master.district_id)
    rows = []
    for i, e in enumerate(entries):
        if e.get("region"):
            if e["region"] not in regions:
                raise ValueError(f"unknown region {e['region']!r}")
            ids = list(regions[e["region"]]["district_ids"])
            missing = set(ids) - known
            if missing:
                raise ValueError(f"region {e['region']}: districts {sorted(missing)} not in "
                                 "the district master")
            region_state = regions[e["region"]].get("state")
            if region_state and set(ids) - set(ids_by_state.get(region_state, [])):
                raise ValueError(f"region {e['region']}: districts outside {region_state}")
        elif e["state"] == "ALL":
            ids = sorted(known)
        elif e["state"] in states:
            ids = ids_by_state[e["state"]]
        else:
            raise ValueError(f"unknown Census 2011 state {e['state']!r}")
        q = pd.Period(pd.Timestamp(e[date_key]), "Q").end_time.normalize()
        rows += [(i, d, q) for d in ids]
    return pd.DataFrame(rows, columns=["entry", "district_id", "quarter_end"]).astype(
        {"entry": int, "district_id": int, "quarter_end": "datetime64[ns]"})


def _flag(grid: pd.DataFrame, ev: pd.DataFrame, name: str) -> pd.DataFrame:
    hit = ev[["district_id", "quarter_end"]].drop_duplicates().assign(**{name: True})
    out = grid.merge(hit, on=["district_id", "quarter_end"], how="left")
    out[name] = out[name].astype("boolean").fillna(False).astype(bool)
    return out


def _qidx(ts: pd.Series) -> pd.Series:
    return ts.dt.year * 4 + ts.dt.quarter


def waiver_flags(waivers: list[dict], master: pd.DataFrame, quarters: list[pd.Timestamp],
                 regions: dict | None = None) -> pd.DataFrame:
    """Per district and quarter: commercial-bank waiver announced, cooperative-only waiver
    announced, and quarters since the latest commercial-bank waiver (null before any)."""
    ev = event_districts(waivers, master, "announced", regions)
    coop = pd.Series([("cooperative" in str(w.get("scope", "")).lower()) for w in waivers],
                     dtype=bool)
    is_coop = ev.entry.map(coop).astype(bool) if len(ev) else pd.Series([], dtype=bool)
    grid = _flag(_grid(master, quarters), ev[~is_coop], "waiver_commercial")
    grid = _flag(grid, ev[is_coop], "waiver_coop_only")
    grid = grid.sort_values(["district_id", "quarter_end"])
    q = _qidx(grid.quarter_end)
    last = q.where(grid.waiver_commercial).groupby(grid.district_id).ffill()
    grid["quarters_since_waiver"] = (q - last).astype("Int64")
    return grid


def election_flags(assembly: list[dict], general: list[str], master: pd.DataFrame,
                   quarters: list[pd.Timestamp], regions: dict | None = None) -> pd.DataFrame:
    """Per district and quarter: state assembly election results declared in the quarter,
    Lok Sabha results declared in the quarter, and quarters until the next assembly results
    (0 in the results quarter; null when no later election is listed, and always null in
    union territories without an assembly)."""
    ev = event_districts(assembly, master, "results", regions)
    gen = event_districts([{"state": "ALL", "results": d} for d in general], master,
                          "results")
    grid = _flag(_grid(master, quarters), ev, "election_state")
    grid = _flag(grid, gen, "election_general")
    grid = grid.sort_values(["district_id", "quarter_end"])
    # the next results quarter may fall after the study window, so look it up in the
    # event list rather than in the grid
    nxt = ev[["district_id", "quarter_end"]].drop_duplicates().sort_values("quarter_end")
    nxt = nxt.rename(columns={"quarter_end": "next_results"})
    # pandas 3 keeps microseconds where pandas 2 used nanoseconds, and merge_asof needs both
    # keys in the same unit (an empty event list comes out in nanoseconds)
    nxt["next_results"] = nxt.next_results.astype(grid.quarter_end.dtype)
    grid = pd.merge_asof(grid.sort_values("quarter_end"), nxt, by="district_id",
                         left_on="quarter_end", right_on="next_results",
                         direction="forward")
    grid["quarters_to_state_election"] = (
        _qidx(grid.next_results) - _qidx(grid.quarter_end)).astype("Int64")
    return grid.drop(columns="next_results").sort_values(["district_id", "quarter_end"])


def shock_flags(shocks: list[dict], master: pd.DataFrame, quarters: list[pd.Timestamp],
                regions: dict | None = None) -> pd.DataFrame:
    """Per district and quarter: a large state policy shock began in the quarter, and its
    name (names joined by '; ' when two fall in one quarter)."""
    ev = event_districts(shocks, master, "date", regions)
    names = pd.Series([s["name"] for s in shocks], dtype=object)
    ev = ev.assign(name=ev.entry.map(names))
    grid = _flag(_grid(master, quarters), ev, "state_shock")
    nm = ev.groupby(["district_id", "quarter_end"]).name.agg("; ".join) \
        .rename("state_shock_name").reset_index()
    return grid.merge(nm, on=["district_id", "quarter_end"], how="left")


def build_controls(master: pd.DataFrame, census: pd.DataFrame, raw_dir: Path, cfg: dict,
                   quarters: list[pd.Timestamp], data_version: str) -> pd.DataFrame:
    grid = pd.MultiIndex.from_product([sorted(master.district_id), quarters],
                                      names=["district_id", "quarter_end"]).to_frame(index=False)
    out = grid.merge(census_controls(census, master), on="district_id", how="left")
    normal = tuple(cfg.get("rain_normal", [1991, 2020]))
    rain = rain_quarterly(read_ee_tables(raw_dir, "rain"), normal)
    ntl = ntl_quarterly(read_ee_tables(raw_dir, "ntl_viirs"))
    harm = ntl_annual(read_ee_tables(raw_dir, "ntl_harmonized"))
    out = out.merge(rain, on=["district_id", "quarter_end"], how="left")
    out = out.merge(ntl, on=["district_id", "quarter_end"], how="left")
    out["year"] = out.quarter_end.dt.year
    out = out.merge(harm, on=["district_id", "year"], how="left").drop(columns="year")
    regions = cfg.get("regions", {})
    keys = ["district_id", "quarter_end"]
    out = out.merge(waiver_flags(cfg.get("loan_waivers", []), master, quarters, regions),
                    on=keys, how="left")
    out = out.merge(election_flags(cfg.get("state_elections", []),
                                   cfg.get("general_elections", []), master, quarters,
                                   regions), on=keys, how="left")
    out = out.merge(shock_flags(cfg.get("state_shocks", []), master, quarters, regions),
                    on=keys, how="left")
    for c in ["rain_mm", "rain_anom", "ntl_viirs", "ntl_harmonized"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)
    out["data_version"] = data_version
    return out.sort_values(["district_id", "quarter_end"]).reset_index(drop=True)


def study_quarters() -> list[pd.Timestamp]:
    end = pd.Timestamp(config.load("project")["study_period"]["end"])
    return list(pd.date_range("2004-03-31", end, freq="QE"))


def build(out: Path | None = None) -> Path:
    from cri.exposure.panel import data_version
    from cri.geo.district_master import census_path

    out = out or config.path("processed") / CONTROLS_FILE
    master = pd.read_parquet(config.path("district_geometry.preferred"),
                             columns=["district_id", "state", "population", "urban_share"])
    census = pd.read_csv(census_path())
    controls = build_controls(master, census, config.path("raw_layers.controls"),
                              config.load("controls"), study_quarters(), data_version())
    controls.to_parquet(out, index=False)
    filled = {c: f"{controls[c].notna().mean():.0%}"
              for c in ["rain_mm", "ntl_viirs", "ntl_harmonized"]}
    log.info("controls: %d rows; filled %s; written to %s", len(controls), filled, out)
    return out


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    print(build())


if __name__ == "__main__":
    main()
