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
    wide = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    if wide.district_id.duplicated().any():
        raise ValueError(f"{product}: a district appears in two batch files")
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
    if monthly.empty:
        return pd.DataFrame(columns=["district_id", "quarter_end", "ntl_viirs"])
    m = monthly.assign(quarter_end=quarter_end(monthly.period))
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


def waiver_flags(waivers: list[dict], master: pd.DataFrame,
                 quarters: list[pd.Timestamp]) -> pd.DataFrame:
    """Per district and quarter: commercial-bank waiver announced, cooperative-only waiver
    announced, and quarters since the latest commercial-bank waiver (null before any)."""
    states = sorted(master.state.unique())
    rows = []
    for w in waivers:
        targets = states if w["state"] == "ALL" else [w["state"]]
        unknown = set(targets) - set(states)
        if unknown:
            raise ValueError(f"loan_waivers: unknown Census 2011 state {sorted(unknown)}")
        q = pd.Period(pd.Timestamp(w["announced"]), "Q").end_time.normalize()
        coop = "cooperative" in str(w["scope"]).lower()
        rows += [{"state": s, "quarter_end": q, "coop": coop} for s in targets]
    ev = pd.DataFrame(rows, columns=["state", "quarter_end", "coop"]).astype(
        {"state": object, "quarter_end": "datetime64[ns]", "coop": bool})
    grid = pd.MultiIndex.from_product([states, quarters], names=["state", "quarter_end"]) \
        .to_frame(index=False)
    comm = ev[~ev.coop].drop_duplicates(["state", "quarter_end"]).assign(waiver_commercial=True)
    coop = ev[ev.coop].drop_duplicates(["state", "quarter_end"]).assign(waiver_coop_only=True)
    grid = grid.merge(comm[["state", "quarter_end", "waiver_commercial"]], how="left") \
        .merge(coop[["state", "quarter_end", "waiver_coop_only"]], how="left")
    grid[["waiver_commercial", "waiver_coop_only"]] = grid[
        ["waiver_commercial", "waiver_coop_only"]].fillna(False).astype(bool)
    grid = grid.sort_values(["state", "quarter_end"])
    qidx = grid.quarter_end.dt.year * 4 + grid.quarter_end.dt.quarter
    last = qidx.where(grid.waiver_commercial).groupby(grid.state).ffill()
    grid["quarters_since_waiver"] = (qidx - last).astype("Int64")
    out = master[["district_id", "state"]].merge(grid, on="state")
    return out.drop(columns="state")


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
    out = out.merge(waiver_flags(cfg.get("loan_waivers", []), master, quarters),
                    on=["district_id", "quarter_end"], how="left")
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
