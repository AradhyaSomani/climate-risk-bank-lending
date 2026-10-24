"""Read-only API over the project's tables (Phase 5A).

Every response is an envelope:

    {"resource": ..., "data_version": ..., "source": "parquet" | "sample" | "postgres",
     "n": <rows>, "rows": [...], ...}

plus, where it applies, the estimators (effects) or routes (exposure) present in the rows.
Stress numbers are never served without their interval: rows of `stress_results` with a
missing `lower` or `upper` are withheld and counted in `withheld_without_interval`.
Nothing here writes.

    CRI_API_SOURCE=sample uvicorn cri.api.app:app        # runs on a clean checkout
    uvicorn cri.api.app:app                               # data/processed
    CRI_API_SOURCE=postgres DATABASE_URL=... uvicorn cri.api.app:app
"""

from __future__ import annotations

import math
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query

from cri import config
from cri.api import store as stores

INTERVALS = {"effects": ("ci_low", "ci_high"), "stress_results": ("lower", "upper"),
             "exposure": ("share_low", "share_high")}


def _value(v: Any) -> Any:
    if v is None or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(v).date().isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def records(df: pd.DataFrame) -> list[dict]:
    cols = list(df.columns)
    return [{c: _value(v) for c, v in zip(cols, row, strict=True)}
            for row in df.itertuples(index=False, name=None)]


def filt(df: pd.DataFrame, **eq) -> pd.DataFrame:
    for col, val in eq.items():
        if val is None or col not in df:
            continue
        if isinstance(val, list):
            df = df[df[col].isin(val)]
        else:
            df = df[df[col].astype(str) == str(val)]
    return df


def create_app(store=None) -> FastAPI:
    store = store or stores.from_env()
    app = FastAPI(title="Climate risk in Indian bank lending",
                  description=__doc__, version="0.1.0")
    fallback_version = config.load("project").get("data_version", "dev")

    def source() -> str:
        return getattr(store, "last_source", store.name)

    def table(resource: str) -> pd.DataFrame:
        try:
            return store.table(resource)
        except stores.Missing as e:
            raise HTTPException(404, f"{resource}: {e}") from e

    def envelope(resource: str, df: pd.DataFrame, **extra) -> dict:
        if "data_version" in df and df.data_version.notna().any():
            versions = sorted(df.data_version.dropna().astype(str).unique())
            version = versions[0] if len(versions) == 1 else versions
        else:
            version = fallback_version
        lo_hi = INTERVALS.get(resource)
        if lo_hi:
            extra["interval"] = {"lower": lo_hi[0], "upper": lo_hi[1]}
        if "estimator" in df:
            extra["estimators"] = sorted(df.estimator.dropna().unique().tolist())
        if "route" in df:
            extra["routes"] = sorted(df.route.dropna().unique().tolist())
        return {"resource": resource, "data_version": version, "source": source(),
                "n": len(df), **extra, "rows": records(df)}

    @app.get("/health")
    def health() -> dict:
        have = {}
        for r in stores.RESOURCES:
            try:
                have[r] = len(store.table(r))
            except stores.Missing:
                have[r] = None
        return {"status": "ok", "source": source(), "data_version": fallback_version,
                "tables": have}

    @app.get("/districts")
    def districts(state: str | None = None, geometry: bool = False,
                  simplify_deg: Annotated[float, Query(ge=0, le=0.1)] = 0.01) -> dict:
        d = store.districts()
        d = filt(d, state=state)
        cols = [c for c in ("district_id", "name", "state", "area_km2", "population")
                if c in d]
        out = envelope("districts", pd.DataFrame(d[cols]))
        if geometry:
            out["geojson"] = geojson(d, cols, simplify_deg)
        return out

    @app.get("/hazard-scores")
    def hazard_scores(hazard_type: str | None = None, score_version: str | None = None,
                      district_id: Annotated[list[int] | None, Query()] = None,
                      tier: int | None = None) -> dict:
        df = filt(table("hazard_scores"), hazard_type=hazard_type,
                  score_version=score_version, district_id=district_id, tier=tier)
        return envelope("hazard_scores", df)

    @app.get("/hazard-indicators")
    def hazard_indicators(district_id: Annotated[list[int] | None, Query()] = None) -> dict:
        return envelope("hazard_indicators",
                        filt(table("hazard_indicators"), district_id=district_id))

    @app.get("/events")
    def events(hazard_type: str | None = None) -> dict:
        return envelope("events", filt(table("events"), hazard_type=hazard_type))

    @app.get("/events/{event_id}/districts")
    def event_districts(event_id: str, treated: bool | None = None) -> dict:
        df = filt(table("event_district"), event_id=event_id)
        if df.empty:
            raise HTTPException(404, f"no districts for event {event_id}")
        if treated is not None:
            df = df[df.treated == treated]
        return envelope("event_district", df)

    @app.get("/scenarios")
    def scenarios(scenario_type: str | None = None) -> dict:
        return envelope("scenarios", filt(table("scenarios"), scenario_type=scenario_type))

    @app.get("/scenarios/{scenario_id}/districts")
    def scenario_districts(scenario_id: str) -> dict:
        df = filt(table("scenario_district"), scenario_id=scenario_id)
        if df.empty:
            raise HTTPException(404, f"no footprint for scenario {scenario_id}")
        sc = filt(table("scenarios"), scenario_id=scenario_id)
        hyp = bool(sc.hypothetical.iloc[0]) if len(sc) and "hypothetical" in sc else None
        return envelope("scenario_district", df, hypothetical=hyp)

    @app.get("/exposure")
    def exposure(bank_group: str | None = None, sector: str | None = None,
                 route: str | None = None, quarter_end: str | None = None) -> dict:
        df = table("exposure")
        if quarter_end is not None:
            df = df[pd.to_datetime(df.quarter_end) == pd.Timestamp(quarter_end)]
        return envelope("exposure", filt(df, bank_group=bank_group, sector=sector,
                                         route=route))

    @app.get("/effects")
    def effects(event_id: str | None = None, estimator: str | None = None,
                outcome: str | None = None, bank_group: str | None = None) -> dict:
        df = filt(table("effects"), event_id=event_id, estimator=estimator, outcome=outcome,
                  bank_group=bank_group)
        return envelope("effects", df)

    @app.get("/stress-results")
    def stress_results(scenario_id: str | None = None, bank_group: str | None = None,
                       metric: str | None = None, horizon: str | None = None) -> dict:
        df = filt(table("stress_results"), scenario_id=scenario_id, bank_group=bank_group,
                  metric=metric, horizon=horizon)
        ok = df["lower"].notna() & df["upper"].notna() & df["median"].notna()
        return envelope("stress_results", df[ok], withheld_without_interval=int((~ok).sum()))

    @app.get("/model-runs")
    def model_runs(component: str | None = None) -> dict:
        return envelope("model_runs", filt(table("model_runs"), component=component))

    return app


def geojson(d: pd.DataFrame, cols: list[str], simplify_deg: float) -> dict:
    """FeatureCollection from shapely geometries or WKT strings, simplified for the map."""
    import shapely

    geom = d["geometry"] if "geometry" in d else None
    if geom is None:
        return {"type": "FeatureCollection", "features": []}
    g = np.asarray([shapely.from_wkt(x) if isinstance(x, str) else x for x in geom])
    if simplify_deg:
        g = shapely.simplify(g, simplify_deg, preserve_topology=True)
    props = records(pd.DataFrame(d[cols]))
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": p, "geometry": shapely.geometry.mapping(x)}
        for p, x in zip(props, g, strict=True)]}


def __getattr__(name: str):
    # `uvicorn cri.api.app:app` builds the app on first use, so importing this module
    # (tests, docs) does not touch any store
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
