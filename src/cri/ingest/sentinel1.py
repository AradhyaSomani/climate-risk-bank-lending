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

    python -m cri.ingest.sentinel1 --event FL-2018-KERALA --bbox 74.8 8.2 77.5 12.9 \
        --pre 2018-06-01 2018-07-31 --post 2018-08-14 2018-08-24 --bucket my-gcs-bucket

`--kind backscatter` exports the post-event VV and VH (dB, 10 m) plus `jrc_perm_water`
instead, as the input scene for the U-Net (`cri.ml.flood_cnn.predict`). Keep the box small
at 10 m: central Kerala (76.2 9.0 76.9 10.3) is about 1.3 GB.
"""

from __future__ import annotations

import argparse

DEFAULTS = {"diff_db": -3.0, "slope_max_deg": 5.0, "scale_m": 30, "perm_occurrence": 90}


def _ee():
    import ee  # imported lazily: optional dependency

    ee.Initialize()
    return ee


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


def flood_image(bbox, pre, post, orbit: str = "DESCENDING", **kw):
    ee = _ee()
    p = {**DEFAULTS, **kw}
    aoi = ee.Geometry.Rectangle(list(bbox))
    s1 = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(aoi)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.eq("orbitProperties_pass", orbit))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .select("VV")
    )
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
        water.rename("flooded").toFloat()
        .addBands(perm.rename("jrc_perm_water").toFloat())
        .clip(aoi)
        .set({"otsu_threshold_db": threshold, "pre": pre, "post": post, "orbit": orbit})
    )


def backscatter_image(bbox, post, orbit: str = "DESCENDING", perm_occurrence: int = 90):
    """Post-event minimum VV and VH (dB) and JRC permanent water, for the U-Net."""
    ee = _ee()
    aoi = ee.Geometry.Rectangle(list(bbox))
    s1 = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(aoi)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.eq("orbitProperties_pass", orbit))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .select(["VV", "VH"])
        .filterDate(*post)
    )
    perm = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").gte(perm_occurrence)
    return (s1.min().toFloat().addBands(perm.unmask(0).rename("jrc_perm_water").toFloat())
            .clip(aoi).set({"post": post, "orbit": orbit}))


def export(event_id: str, bbox, pre, post, bucket: str, orbit: str = "DESCENDING",
           kind: str = "otsu") -> object:
    ee = _ee()
    if kind == "backscatter":
        img, scale = backscatter_image(bbox, post, orbit), 10
    else:
        img, scale = flood_image(bbox, pre, post, orbit), DEFAULTS["scale_m"]
    task = ee.batch.Export.image.toCloudStorage(
        image=img,
        description=f"s1_{kind}_{event_id}",
        bucket=bucket,
        fileNamePrefix=f"sentinel1/{event_id}_s1_{kind}",
        region=ee.Geometry.Rectangle(list(bbox)),
        scale=scale,
        crs="EPSG:4326",
        maxPixels=1e11,
    )
    task.start()
    return task


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--event", required=True)
    p.add_argument("--bbox", type=float, nargs=4, required=True, metavar=("W", "S", "E", "N"))
    p.add_argument("--pre", nargs=2, required=True)
    p.add_argument("--post", nargs=2, required=True)
    p.add_argument("--orbit", default="DESCENDING", choices=["ASCENDING", "DESCENDING"])
    p.add_argument("--bucket", required=True, help="GCS bucket for the export")
    p.add_argument("--kind", default="otsu", choices=["otsu", "backscatter"])
    a = p.parse_args(argv)
    task = export(a.event, a.bbox, a.pre, a.post, a.bucket, a.orbit, a.kind)
    print(f"started Earth Engine task {task.id}; download the GeoTIFF to data/raw/sentinel1/")


if __name__ == "__main__":
    main()
