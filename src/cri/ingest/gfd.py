"""Global Flood Database v1 (Tellman et al. 2021) from its public Cloud Storage bucket.

The Earth Engine collection GLOBAL_FLOOD_DB/MODIS_EVENTS/V1 is also published as one zip per
event in the public bucket `gfd_v1_4`: a 5-band GeoTIFF (flooded, duration, clear_views,
clear_perc, jrc_perm_water) at about 250 m (0.002246 degrees), a properties JSON, the README
and the CC BY-NC 4.0 licence. No Earth Engine account is needed.

    python -m cri.ingest.gfd index --out data/raw/gfd/gfd_events.csv
    python -m cri.ingest.gfd fetch 4309 --dest data/raw/gfd
"""

from __future__ import annotations

import argparse
import io
import json
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

BUCKET = "gfd_v1_4"
LIST_URL = "https://storage.googleapis.com/storage/v1/b/{bucket}/o"
OBJECT_URL = "https://storage.googleapis.com/{bucket}/{name}"
BANDS = ("flooded", "duration", "clear_views", "clear_perc", "jrc_perm_water")


def list_objects(bucket: str = BUCKET) -> list[dict]:
    """All objects in the bucket as [{'name', 'size'}]."""
    items, token = [], None
    while True:
        url = LIST_URL.format(bucket=bucket)
        url += "?maxResults=1000&fields=nextPageToken,items(name,size)"
        if token:
            url += f"&pageToken={token}"
        with urllib.request.urlopen(url, timeout=60) as r:
            page = json.load(r)
        items += page.get("items", [])
        token = page.get("nextPageToken")
        if not token:
            return items


class _RangeFile(io.RawIOBase):
    """Read-only file over HTTP range requests, enough for zipfile to read one member."""

    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos = url, size, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size or len(b) == 0:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        b[: len(data)] = data
        self.pos += len(data)
        return len(data)


def read_properties(name: str, size: int, bucket: str = BUCKET, retries: int = 3) -> dict:
    """Read the event's properties JSON without downloading the raster."""
    url = OBJECT_URL.format(bucket=bucket, name=name)
    err: Exception | None = None
    for _ in range(retries):
        try:
            zf = zipfile.ZipFile(io.BufferedReader(_RangeFile(url, int(size)), 1 << 16))
            member = next(n for n in zf.namelist() if n.endswith("_properties.json"))
            props = json.loads(zf.read(member))
            props.update(zip_name=name, zip_bytes=int(size))
            return props
        except Exception as e:  # network hiccups: retry
            err = e
    raise RuntimeError(f"could not read properties of {name}: {err}")


def build_index(workers: int = 16) -> pd.DataFrame:
    """One row per GFD event with the DFO properties (country codes, dates, deaths, cause)."""
    objs = [o for o in list_objects() if o["name"].endswith(".zip")]
    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(lambda o: read_properties(o["name"], o["size"]), objs))
    df = pd.DataFrame(rows).rename(columns={"id": "dfo_id"})
    df["began"] = pd.to_datetime(df["began"])
    df["ended"] = pd.to_datetime(df["ended"])
    return df.sort_values("began").reset_index(drop=True)


def india_events(index: pd.DataFrame) -> pd.DataFrame:
    """Events whose detected flood water touches India (cc lists every country with water)."""
    hit = index["cc"].fillna("").str.split(r",\s*").map(lambda cs: "IND" in cs)
    cols = [
        "dfo_id", "began", "ended", "cc", "dfo_country", "dfo_main_cause", "dfo_dead",
        "dfo_displaced", "dfo_severity", "dfo_centroid_x", "dfo_centroid_y", "glide_index",
        "zip_name", "zip_bytes",
    ]
    return index.loc[hit, [c for c in cols if c in index]].reset_index(drop=True)


def fetch_event(dfo_id: int, dest: Path, index: pd.DataFrame | None = None) -> Path:
    """Download and unzip one event into dest/DFO_<id>/; returns the GeoTIFF path."""
    if index is None:
        objs = list_objects()
        name = next(o["name"] for o in objs if o["name"].startswith(f"DFO_{dfo_id}_"))
    else:
        name = index.loc[index.dfo_id == dfo_id, "zip_name"].iloc[0]
    out = Path(dest) / f"DFO_{dfo_id}"
    tifs = list(out.glob("*.tif"))
    if tifs:
        return tifs[0]
    out.mkdir(parents=True, exist_ok=True)
    zpath = out / name
    urllib.request.urlretrieve(OBJECT_URL.format(bucket=BUCKET, name=name), zpath)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(out)
    zpath.unlink()
    return next(out.glob("*.tif"))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("index", help="list every event with its properties")
    pi.add_argument("--out", type=Path, required=True)
    pi.add_argument("--india-out", type=Path, help="also write the India subset here")
    pf = sub.add_parser("fetch", help="download one event")
    pf.add_argument("dfo_id", type=int)
    pf.add_argument("--dest", type=Path, default=Path("data/raw/gfd"))
    a = p.parse_args(argv)

    if a.cmd == "index":
        idx = build_index()
        a.out.parent.mkdir(parents=True, exist_ok=True)
        idx.to_csv(a.out, index=False)
        print(f"{len(idx)} events -> {a.out}")
        if a.india_out:
            ind = india_events(idx)
            ind.to_csv(a.india_out, index=False)
            print(f"{len(ind)} India events -> {a.india_out}")
    else:
        print(fetch_event(a.dfo_id, a.dest))


if __name__ == "__main__":
    main()
