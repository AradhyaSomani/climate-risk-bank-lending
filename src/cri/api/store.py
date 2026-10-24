"""Where the API reads its tables from.

Three stores, all returning plain DataFrames with the column names of the contracts:

- `ParquetStore`: the files in data/processed (the source of truth).
- `SampleStore`: the toy samples of the contracts in tests/fixtures/contracts, so the API
  and the dashboard run on a clean checkout with no data at all.
- `PostgresStore`: the warehouse loaded by `cri.db.load` (needs the `db` extra).

`from_env` picks one from CRI_API_SOURCE (parquet | sample | postgres; default parquet,
falling back to the samples table by table when a file is missing and CRI_API_FALLBACK=1).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cri import config, contracts


@dataclass(frozen=True)
class Resource:
    file: str  # file name in data/processed
    db_table: str  # table name in the warehouse
    contract: tuple[str, str] | None = None  # (contract id, table) when one exists


RESOURCES = {
    "hazard_scores": Resource("hazard_scores.parquet", "hazard_score", ("C3", "hazard_scores")),
    "hazard_indicators": Resource("hazard_indicators.parquet", "hazard_indicators",
                                  ("C3", "hazard_indicators")),
    "events": Resource("events.parquet", "hazard_event", ("C4", "events")),
    "event_district": Resource("event_district.parquet", "event_district",
                               ("C4", "event_district")),
    "scenarios": Resource("scenarios.parquet", "scenario", ("C4", "scenarios")),
    "scenario_district": Resource("scenario_district.parquet", "scenario_district",
                                  ("C4", "scenario_district")),
    "exposure": Resource("exposure.parquet", "exposure"),
    "effects": Resource("effects.parquet", "effect", ("C5", "effects")),
    "stress_results": Resource("stress_results.parquet", "stress_result",
                               ("C5", "stress_results")),
    "model_runs": Resource("model_runs.parquet", "model_run"),
}


class Missing(LookupError):
    """The table has not been built yet (or is not in this store)."""


class ParquetStore:
    name = "parquet"

    def __init__(self, processed: Path | None = None):
        self.processed = Path(processed or config.path("processed"))
        self._cache: dict[str, tuple[float, pd.DataFrame]] = {}

    def table(self, resource: str) -> pd.DataFrame:
        r = RESOURCES[resource]
        path = self.processed / r.file
        if resource == "model_runs":
            path = config.path("ml.model_runs")
        if not path.exists():
            raise Missing(f"{r.file} not built yet")
        mtime = path.stat().st_mtime
        hit = self._cache.get(resource)
        if hit is None or hit[0] != mtime:  # re-read when the file changes
            hit = (mtime, pd.read_parquet(path))
            self._cache[resource] = hit
        return hit[1]

    def districts(self) -> pd.DataFrame:
        from cri.geo.districts import load_districts

        return load_districts()


class SampleStore:
    name = "sample"

    def table(self, resource: str) -> pd.DataFrame:
        r = RESOURCES[resource]
        if r.contract is None:
            raise Missing(f"no sample for {resource}")
        spec = contracts.get_table(*r.contract)
        return contracts.read_table(contracts.REPO_ROOT / spec.sample, spec)

    def districts(self) -> pd.DataFrame:
        spec = contracts.get_table("C1", "district_master")
        return contracts.read_table(contracts.REPO_ROOT / spec.sample, spec)


class FallbackStore:
    """Parquet first, the contract sample when the file is missing."""

    def __init__(self, primary: ParquetStore, sample: SampleStore):
        self.primary, self.sample = primary, sample
        self.name = "parquet"
        self.last_source = "parquet"

    def table(self, resource: str) -> pd.DataFrame:
        try:
            df = self.primary.table(resource)
            self.last_source = "parquet"
        except Missing:
            df = self.sample.table(resource)
            self.last_source = "sample"
        return df

    def districts(self) -> pd.DataFrame:
        try:
            return self.primary.districts()
        except Exception:  # no geometry downloaded: the sample master has none either
            return self.sample.districts()


class PostgresStore:
    name = "postgres"

    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get("DATABASE_URL")

    def _query(self, sql: str) -> pd.DataFrame:
        from cri.db.load import connect

        with connect(self.url) as conn, conn.cursor() as cur:
            try:
                cur.execute(sql)
            except Exception as e:  # undefined table and the like
                raise Missing(str(e).splitlines()[0]) from e
            cols = [c.name for c in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)

    def table(self, resource: str) -> pd.DataFrame:
        df = self._query(f"SELECT * FROM {RESOURCES[resource].db_table}")  # names are ours
        if df.empty:
            raise Missing(f"{RESOURCES[resource].db_table} is empty")
        return df

    def districts(self) -> pd.DataFrame:
        import geopandas as gpd
        import shapely

        df = self._query("SELECT district_id, name, state, ST_AsBinary(geom) AS geom "
                         "FROM district")
        geom = shapely.from_wkb([bytes(g) for g in df.pop("geom")])
        return gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")


def from_env():
    src = os.environ.get("CRI_API_SOURCE", "parquet")
    if src == "sample":
        return SampleStore()
    if src == "postgres":
        return PostgresStore()
    if src != "parquet":
        raise ValueError(f"CRI_API_SOURCE must be parquet, sample or postgres, not {src!r}")
    if os.environ.get("CRI_API_FALLBACK") == "1":
        return FallbackStore(ParquetStore(), SampleStore())
    return ParquetStore()
