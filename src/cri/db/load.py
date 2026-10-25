"""Load processed tables into PostgreSQL + PostGIS (Phase 1I).

Idempotent: the schema uses IF NOT EXISTS, and every table is loaded through a temporary
table and an upsert on its primary key, with rows that are no longer in the file removed.
Running it twice gives the same database. Tables whose file does not exist yet are skipped.

    DATABASE_URL=postgresql://user@localhost:5432/cri python scripts/load_db.py
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import MultiPolygon, Polygon

from cri import config

log = logging.getLogger(__name__)

SCHEMA = Path(__file__).with_name("schema.sql")
DEFAULT_URL = "postgresql://postgres@localhost:5432/cri"


@dataclass
class Target:
    table: str
    file: str | None  # file in data/processed (None = built in code)
    key: list[str] = field(default_factory=list)  # empty = replace the whole table
    rename: dict[str, str] = field(default_factory=dict)
    prune: bool = True  # delete rows absent from the file (off for district: FK parents)


# load order respects foreign keys
TARGETS = [
    Target("district", None, ["district_id"], prune=False),
    Target("district_crosswalk", "crosswalk_rbi_to_c2011.parquet",
           ["rbi_name", "rbi_state", "valid_from", "district_id"]),
    Target("district_edge", "district_edges.parquet", ["a", "b"]),
    Target("credit_deposit", "panel_credit_deposit.parquet",
           ["district_id", "quarter_end", "bank_group", "measure", "sector"]),
    Target("control_var", "controls_district_quarter.parquet", ["district_id", "quarter_end"]),
    Target("hazard_event", "events.parquet", ["event_id"]),
    Target("event_district", "event_district.parquet", ["event_id", "district_id"]),
    Target("hazard_score", "hazard_scores.parquet",
           ["district_id", "score_version", "hazard_type"]),
    Target("flood_extent", "flood_extent_district_event.parquet",
           ["event_id", "district_id", "source"]),
    Target("cyclone_exposure", "cyclone_exposure_district_event.parquet",
           ["event_id", "district_id"]),
    Target("hazard_baseline", "hazard_baseline_district.parquet", ["district_id"]),
    Target("exposure", "exposure.parquet",
           ["quarter_end", "bank_group", "sector", "tier", "route"]),
    Target("effect", "effects.parquet", [], rename={"primary": "is_primary"}),
    Target("scenario", "scenarios.parquet", ["scenario_id"]),
    Target("scenario_district", "scenario_district.parquet", ["scenario_id", "district_id"]),
    Target("stress_result", "stress_results.parquet",
           ["scenario_id", "bank_group", "metric", "horizon"]),
    Target("model_run", "model_runs.parquet", ["run_id"]),
]


def connect(url: str | None = None):
    import psycopg  # optional dependency: pip install -e .[db]

    return psycopg.connect(url or os.environ.get("DATABASE_URL", DEFAULT_URL))


def apply_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA.read_text())
    conn.commit()


def table_columns(conn, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def as_multipolygon(geom):
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    parts = [p for g in polys for p in (g.geoms if isinstance(g, MultiPolygon) else [g])]
    return MultiPolygon(parts)


def district_frame() -> pd.DataFrame:
    """District rows from B's master if present, otherwise the provisional geometry."""
    master = config.path("processed") / "district_master.parquet"
    if master.exists():
        import geopandas as gpd

        gdf = gpd.read_parquet(master)
    else:
        from cri.geo.districts import load_districts

        gdf = load_districts()
    df = pd.DataFrame(gdf.drop(columns="geometry"))
    df["geom"] = [
        shapely.to_wkb(as_multipolygon(g), hex=True, include_srid=True)
        for g in shapely.set_srid(gdf.geometry.to_numpy(), 4326)
    ]
    return df


def _clean(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, np.generic):
        v = v.item()
        return None if isinstance(v, float) and math.isnan(v) else v
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, (datetime, date, str, int, float, bool)):
        return v
    return v


def load_frame(conn, t: Target, df: pd.DataFrame) -> int:
    cols_db = table_columns(conn, t.table)
    df = df.rename(columns=t.rename)
    cols = [c for c in cols_db if c in df.columns]
    missing = [c for c in t.key if c not in cols]
    if missing:
        raise ValueError(f"{t.table}: file lacks key columns {missing}")
    rows = df[cols].astype(object).itertuples(index=False, name=None)
    collist = ", ".join(cols)
    with conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE _load (LIKE {t.table} INCLUDING DEFAULTS) ON COMMIT DROP")
        with cur.copy(f"COPY _load ({collist}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row([_clean(v) for v in r])
        if not t.key:
            cur.execute(f"DELETE FROM {t.table}")
            cur.execute(f"INSERT INTO {t.table} ({collist}) SELECT {collist} FROM _load")
        else:
            keys = ", ".join(t.key)
            if t.prune:
                cur.execute(
                    f"DELETE FROM {t.table} t WHERE NOT EXISTS (SELECT 1 FROM _load l WHERE "
                    + " AND ".join(f"l.{k} = t.{k}" for k in t.key) + ")"
                )
            updates = [c for c in cols if c not in t.key]
            action = (
                "DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in updates)
                if updates else "DO NOTHING"
            )
            cur.execute(
                f"INSERT INTO {t.table} ({collist}) SELECT {collist} FROM _load "
                f"ON CONFLICT ({keys}) {action}"
            )
        cur.execute(f"SELECT count(*) FROM {t.table}")
        n = cur.fetchone()[0]
    conn.commit()
    return n


def load_all(url: str | None = None, processed: Path | None = None) -> dict[str, int]:
    processed = processed or config.path("processed")
    counts = {}
    with connect(url) as conn:
        apply_schema(conn)
        for t in TARGETS:
            if t.file is None:
                df = district_frame()
            else:
                path = processed / t.file
                if not path.exists():
                    continue
                df = pd.read_parquet(path)
            counts[t.table] = load_frame(conn, t, df)
            log.info("%s: %d rows", t.table, counts[t.table])
        with conn.cursor() as cur:
            cur.execute("ANALYZE")
        conn.commit()
    return counts


def build() -> list[Path]:
    """Pipeline hook: load if DATABASE_URL is set, otherwise skip quietly."""
    if not os.environ.get("DATABASE_URL"):
        log.warning("DATABASE_URL not set; skipping the warehouse load")
        return []
    load_all()
    return []
