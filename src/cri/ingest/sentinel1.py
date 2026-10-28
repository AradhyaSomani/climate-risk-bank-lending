"""Sentinel-1 flood extent through Earth Engine (needs `pip install -e .[gee]` and
`earthengine authenticate`).

Builds the Phase 2B-B baseline flood map for one event and exports it as a GeoTIFF with the
same band names as the Global Flood Database (`flooded`, `jrc_perm_water`), so the result
goes through cri.hazard.zonal_stats unchanged:

1. VV backscatter (dB) from IW GRD scenes, one orbit direction, before and during the event.
2. Change detection: post-event minimum minus pre-event median below `diff_db`.
3. Otsu threshold on the post-event VV histogram inside the area of interest.
4. Water if both rules agree; JRC permanent water (occurrence >= 90) reported separately.
5. Steep slopes (> 5 degrees, Copernicus DEM) are masked, as in the GFD algorithm.

Dates, orbit and area come from the event's preset in `configs/hazard.yaml` (`sentinel1`);
the area is the land of the event's states, cut to the preset's `bbox` if it has one.
Options on the command line override the preset. The export goes to the Google Drive folder
`sentinel1.drive_folder` (no Cloud Storage bucket or billing needed), or to a bucket with
`--bucket`. Save the downloaded GeoTIFFs in data/raw/sentinel1/ and run
`python -m cri.hazard.flood_extent --s1`.

    python -m cri.ingest.sentinel1 --event FL-2018-KERALA --project my-ee-project --check
    python -m cri.ingest.sentinel1 --event FL-2018-KERALA --project my-ee-project
    python -m cri.ingest.sentinel1 --event FL-2018-KERALA --project my-ee-project \
        --kind backscatter

`--check` prints how many scenes each orbit has in the two windows and exports nothing.
`--kind backscatter` exports the post-event VV and VH (dB, 10 m) plus `jrc_perm_water`
instead, as the input scene for the U-Net (`cri.ml.flood_cnn.predict`), over the preset's
`backscatter_bbox`. Keep that box small at 10 m: central Kerala is about 1.3 GB.
`--project` can also be set once with the environment variable EARTHENGINE_PROJECT.
"""

from __future__ import annotations

import argparse
import os

import pandas as pd

from cri import config

DEFAULTS = {"diff_db": -3.0, "slope_max_deg": 5.0, "scale_m": 30, "perm_occurrence": 90}
# Value written where no scene covers a pixel; cri.hazard.flood_extent reads it as missing
NODATA = {"otsu": 255, "backscatter": -9999}
_PROJECT: str | None = None


def _ee():
    import ee  # imported lazily: optional dependency

    if _PROJECT:
        ee.Initialize(project=_PROJECT)
    else:
        ee.Initialize()
    return ee


def preset(event_id: str) -> dict:
    """The event's settings from configs/hazard.yaml (empty if it has none)."""
    return dict(config.load("hazard").get("sentinel1", {}).get("events", {}).get(event_id, {}))


def event_area(event_id: str, bbox=None, tolerance: float = 0.005):
    """Land of the event's states (shapely, EPSG:4326), cut to `bbox` when one is given.

    The states come from the candidate event list. Without the Arabian Sea and the Bay of
    Bengal in it, the Otsu histogram separates flood water from land, not sea from land.
    """
    from shapely.geometry import box

    from cri.geo.districts import load_districts

    cand = pd.read_csv(config.REPO_ROOT / config.load("events")["candidates"], dtype=str)
    row = cand[cand.event_id == event_id]
    if row.empty:
        raise ValueError(f"{event_id} is not in {config.load('events')['candidates']}")
    states = row.states.iloc[0].split(";")
    d = load_districts()
    geom = d[d.state.isin(states)].geometry.union_all().simplify(tolerance)
    if bbox is not None:
        geom = geom.intersection(box(*bbox))
    if geom.is_empty:
        raise ValueError(f"the box {bbox} does not overlap {', '.join(states)}")
    return geom


def _geometry(ee, geom):
    from shapely.geometry import mapping

    return ee.Geometry(mapping(geom))


def otsu(histogram) -> object:
    """Otsu threshold from an ee.Dictionary histogram (Earth Engine server-side)."""
    ee = _ee()
    counts = ee.Array(ee.Dictionary(histogram).get("histogram"))
    means = ee.Array(ee.Dictionary(histogram).get("bucketMeans"))
    size = means.length().get([0])
    total = counts.reduce(ee.Reducer.sum(), [0]).get([0])
    mean = counts.multiply(means).reduce(ee.Reducer.sum(), [0]).get([0]).divide(total)
    indices = ee.List.sequence(1, size)

    def between_var(i):
        a = counts.slice(0, 0, i)
        a_count = a.reduce(ee.Reducer.sum(), [0]).get([0])
        a_mean = (
            a.multiply(means.slice(0, 0, i)).reduce(ee.Reducer.sum(), [0]).get([0]).divide(a_count)
        )
        b_count = total.subtract(a_count)
        b_mean = mean.multiply(total).subtract(a_count.multiply(a_mean)).divide(b_count)
        return a_count.multiply(a_mean.subtract(mean).pow(2)).add(
            b_count.multiply(b_mean.subtract(mean).pow(2))
        )

    bss = indices.map(between_var)
    return means.sort(bss).get([-1])


def scenes(aoi, orbit: str, polarisation: str = "VV"):
    ee = _ee()
    return (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(aoi)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.eq("orbitProperties_pass", orbit))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", polarisation))
    )


def flood_image(aoi, pre, post, orbit: str = "DESCENDING", **kw):
    """`aoi`: an ee.Geometry."""
    ee = _ee()
    p = {**DEFAULTS, **kw}
    s1 = scenes(aoi, orbit).select("VV")
    before = s1.filterDate(*pre).median().focal_median(30, "circle", "meters")
    after = s1.filterDate(*post).min().focal_median(30, "circle", "meters")
    hist = after.reduceRegion(
        ee.Reducer.histogram(255, 0.1), aoi, p["scale_m"] * 3, maxPixels=1e10, bestEffort=True
    ).get("VV")
    threshold = otsu(hist)
    dem = ee.ImageCollection("COPERNICUS/DEM/GLO30").select("DEM")
    # mosaic() drops the native projection; restore it so slope is computed at 30 m
    slope = ee.Terrain.slope(dem.mosaic().setDefaultProjection(dem.first().projection()))
    water = after.lt(ee.Number(threshold)).And(after.subtract(before).lt(p["diff_db"]))
    water = water.And(slope.lte(p["slope_max_deg"]))
    perm = (
        ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").gte(p["perm_occurrence"])
    ).unmask(0)
    return (
        water.rename("flooded").toByte()
        .addBands(perm.rename("jrc_perm_water").toByte())
        .clip(aoi)
        .set({"otsu_threshold_db": threshold, "pre": pre, "post": post, "orbit": orbit})
    )


def backscatter_image(aoi, post, orbit: str = "DESCENDING", perm_occurrence: int = 90):
    """Post-event minimum VV and VH (dB) and JRC permanent water, for the U-Net."""
    ee = _ee()
    s1 = scenes(aoi, orbit, "VH").select(["VV", "VH"]).filterDate(*post)
    perm = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").gte(perm_occurrence)
    return (s1.min().toFloat().addBands(perm.unmask(0).rename("jrc_perm_water").toFloat())
            .clip(aoi).set({"post": post, "orbit": orbit}))


def scene_counts(aoi, pre, post) -> pd.DataFrame:
    """Scenes per orbit direction in the before and after windows."""
    rows = []
    for orbit in ("ASCENDING", "DESCENDING"):
        s1 = scenes(aoi, orbit)
        rows.append({"orbit": orbit, "before": s1.filterDate(*pre).size().getInfo(),
                     "after": s1.filterDate(*post).size().getInfo()})
    return pd.DataFrame(rows)


def export(event_id: str, aoi, pre, post, orbit: str = "DESCENDING", kind: str = "otsu",
           folder: str | None = None, bucket: str | None = None) -> object:
    """Start the export task: to the Drive `folder`, or to the Cloud Storage `bucket`."""
    ee = _ee()
    if kind == "backscatter":
        img, scale = backscatter_image(aoi, post, orbit), 10
    else:
        img, scale = flood_image(aoi, pre, post, orbit), DEFAULTS["scale_m"]
    name = f"{event_id}_s1_{kind}"
    common = dict(image=img, description=name, region=aoi.bounds(), scale=scale,
                  crs="EPSG:4326", maxPixels=1e11, fileFormat="GeoTIFF",
                  formatOptions={"noData": NODATA[kind]})
    if bucket:
        task = ee.batch.Export.image.toCloudStorage(
            bucket=bucket, fileNamePrefix=f"sentinel1/{name}", **common)
    else:
        task = ee.batch.Export.image.toDrive(folder=folder, fileNamePrefix=name, **common)
    task.start()
    return task


def main(argv: list[str] | None = None) -> None:
    global _PROJECT
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--event", required=True)
    p.add_argument("--project", default=os.environ.get("EARTHENGINE_PROJECT"),
                   help="Google Cloud project registered for Earth Engine")
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"),
                   help="cut the area to this box (default: the preset's)")
    p.add_argument("--pre", nargs=2)
    p.add_argument("--post", nargs=2)
    p.add_argument("--orbit", choices=["ASCENDING", "DESCENDING"])
    p.add_argument("--kind", default="otsu", choices=["otsu", "backscatter"])
    p.add_argument("--folder", help="Google Drive folder (default: sentinel1.drive_folder)")
    p.add_argument("--bucket", help="export to this Cloud Storage bucket instead of Drive")
    p.add_argument("--check", action="store_true", help="count scenes, export nothing")
    a = p.parse_args(argv)
    _PROJECT = a.project

    s = preset(a.event)
    pre, post = a.pre or s.get("pre"), a.post or s.get("post")
    if not (pre and post):
        p.error(f"{a.event} has no preset in configs/hazard.yaml: give --pre and --post")
    orbit = a.orbit or s.get("orbit", "DESCENDING")
    bbox = a.bbox or (s.get("backscatter_bbox") if a.kind == "backscatter" else None) \
        or s.get("bbox")
    if a.kind == "backscatter" and bbox is None:
        p.error("a backscatter export needs a small box: give --bbox or backscatter_bbox")
    geom = event_area(a.event, bbox)
    ee = _ee()
    aoi = _geometry(ee, geom)
    print(f"{a.event}: area {', '.join(f'{v:.2f}' for v in geom.bounds)}, "
          f"before {pre[0]} to {pre[1]}, after {post[0]} to {post[1]}, orbit {orbit}")
    if a.check:
        print(scene_counts(aoi, pre, post).to_string(index=False))
        return
    folder = a.folder or config.load("hazard").get("sentinel1", {}).get("drive_folder")
    task = export(a.event, aoi, pre, post, orbit, a.kind, folder=folder, bucket=a.bucket)
    where = f"gs://{a.bucket}/sentinel1/" if a.bucket else f"Google Drive folder {folder}"
    print(f"started Earth Engine task {task.id}; when it finishes, copy {a.event}_s1_{a.kind}"
          f"*.tif from {where} to data/raw/sentinel1/")


if __name__ == "__main__":
    main()
