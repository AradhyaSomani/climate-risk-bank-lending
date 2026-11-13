"""District rainfall and night lights through Earth Engine (Phase 1 D; needs
`pip install -e .[gee]` and `earthengine authenticate`, as for cri.ingest.sentinel1).

For each product in `configs/controls.yaml` this builds one image with a band per period
(a month for CHIRPS rainfall and VIIRS night lights, a year for the harmonised DMSP-VIIRS
series), averages every band over each Census 2011 district, and exports the result as a
CSV table to the Google Drive folder `drive_folder`. Districts go up in batches of
`batch_size`, with boundaries simplified by `simplify_deg`, so each request stays small.

    python -m cri.ingest.ee_controls --check                 # what each product holds
    python -m cri.ingest.ee_controls                         # start every export
    python -m cri.ingest.ee_controls --product rain          # one product only

Each task writes `<product>_batch<k>.csv` with a `district_id` column and one column per
period (`p2004_01` for a month, `p2004` for a year). Copy the files to data/raw/controls/;
`make data` reads them (cri.exposure.controls). `--project` or EARTHENGINE_PROJECT names the
Cloud project registered for Earth Engine.
"""

from __future__ import annotations

import argparse
import json
import os

import geopandas as gpd
import pandas as pd

from cri import config

_PROJECT: str | None = None


def _ee():
    import ee  # optional dependency

    if _PROJECT:
        ee.Initialize(project=_PROJECT)
    else:
        ee.Initialize()
    return ee


def periods(start: str, end: str, step: str) -> list[pd.Timestamp]:
    """Period starts from `start` (inclusive) to `end` (exclusive): monthly or yearly."""
    freq = "MS" if step == "month" else "YS"
    return list(pd.date_range(start, pd.Timestamp(end) - pd.Timedelta(days=1), freq=freq))


def band_name(t: pd.Timestamp, step: str) -> str:
    return f"p{t.year}_{t.month:02d}" if step == "month" else f"p{t.year}"


def step_of(product: str) -> str:
    return "year" if product == "ntl_harmonized" else "month"


def district_batches(master: gpd.GeoDataFrame, size: int, simplify_deg: float) -> list[dict]:
    """GeoJSON FeatureCollections of simplified districts, `size` districts each."""
    m = master[["district_id", "geometry"]].sort_values("district_id").reset_index(drop=True)
    m["geometry"] = m.geometry.simplify(simplify_deg, preserve_topology=True)
    out = []
    for i in range(0, len(m), size):
        part = m.iloc[i:i + size]
        out.append(json.loads(part.to_json(drop_id=True)))
    return out


def product_image(ee, name: str, spec: dict):
    """One multi-band image: a band per period, named by band_name()."""
    step = step_of(name)
    starts = periods(spec["start"], spec["end"], step)
    if "collections" in spec:
        col = ee.ImageCollection(spec["collections"][0])
        for c in spec["collections"][1:]:
            col = col.merge(ee.ImageCollection(c))
    else:
        col = ee.ImageCollection(spec["collection"])
    col = col.select(spec["band"])
    bands = []
    for t in starts:
        nxt = t + (pd.DateOffset(months=1) if step == "month" else pd.DateOffset(years=1))
        sub = col.filterDate(t.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d"))
        # rainfall is summed over the days of the month; radiance is averaged. A period
        # with no source image becomes a fully masked band, so the CSV has an empty column
        bn = band_name(t, step)
        agg = (sub.sum() if name == "rain" else sub.mean()).rename(bn)
        empty = ee.Image.constant(0).updateMask(0).rename(bn)
        bands.append(ee.Image(ee.Algorithms.If(sub.size().gt(0), agg, empty)))
    return ee.Image.cat(bands)


def check(ee, products: dict) -> pd.DataFrame:
    """Number of source images and first and last date in each product's window."""
    rows = []
    for name, spec in products.items():
        cols = spec.get("collections") or [spec["collection"]]
        for c in cols:
            col = ee.ImageCollection(c).filterDate(spec["start"], spec["end"])
            n = col.size().getInfo()
            dates = col.aggregate_array("system:time_start").getInfo() if n else []
            rows.append({"product": name, "collection": c, "images": n,
                         "first": pd.to_datetime(min(dates), unit="ms").date() if dates else None,
                         "last": pd.to_datetime(max(dates), unit="ms").date() if dates else None})
    return pd.DataFrame(rows)


def export(ee, name: str, spec: dict, batches: list[dict], folder: str) -> list[object]:
    img = product_image(ee, name, spec)
    reducer = getattr(ee.Reducer, spec.get("reducer", "mean"))()
    tasks = []
    for k, fc_json in enumerate(batches, start=1):
        fc = ee.FeatureCollection(fc_json)
        table = img.reduceRegions(collection=fc, reducer=reducer, scale=spec["scale_m"],
                                  tileScale=4)
        desc = f"{name}_batch{k}"
        task = ee.batch.Export.table.toDrive(
            collection=table.map(lambda f: f.setGeometry(None)), description=desc,
            folder=folder, fileNamePrefix=desc, fileFormat="CSV")
        task.start()
        tasks.append(task)
    return tasks


def main(argv: list[str] | None = None) -> None:
    global _PROJECT
    cfg = config.load("controls")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--project", default=os.environ.get("EARTHENGINE_PROJECT"))
    p.add_argument("--product", choices=sorted(cfg["products"]), action="append",
                   help="only this product (repeatable); default all")
    p.add_argument("--check", action="store_true", help="count source images, export nothing")
    a = p.parse_args(argv)
    _PROJECT = a.project
    products = {k: v for k, v in cfg["products"].items() if not a.product or k in a.product}
    ee = _ee()
    if a.check:
        print(check(ee, products).to_string(index=False))
        return
    master = gpd.read_parquet(config.path("district_geometry.preferred"))
    batches = district_batches(master, cfg["batch_size"], cfg["simplify_deg"])
    for name, spec in products.items():
        tasks = export(ee, name, spec, batches, cfg["drive_folder"])
        print(f"{name}: started {len(tasks)} tasks ({', '.join(t.id for t in tasks)})")
    print(f"When they finish, copy the CSVs from Google Drive folder {cfg['drive_folder']} "
          "to data/raw/controls/ and run make data")


if __name__ == "__main__":
    main()
