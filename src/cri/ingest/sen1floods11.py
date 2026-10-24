"""Sen1Floods11 v1.1 hand-labelled chips from the public bucket (Phase 2B-B).

Downloads the Sentinel-1 chips (VV, VH in dB), the hand labels and the JRC permanent-water
chips into data/raw/s1_labels/<layer>/. About 0.5 GB in all. See
docs/data_cards/sen1floods11.md for coverage and licence (research use with citation; do not
redistribute the chips).

    python -m cri.ingest.sen1floods11
"""

from __future__ import annotations

import argparse
import json
import logging
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cri import config

log = logging.getLogger(__name__)

BUCKET = "sen1floods11"
PREFIX = "v1.1/data/flood_events/HandLabeled/{layer}/"
LAYERS = ["S1Hand", "LabelHand", "JRCWaterHand"]
API = "https://storage.googleapis.com/storage/v1/b/{bucket}/o?{query}"
DOWNLOAD = "https://storage.googleapis.com/{bucket}/{name}"


def list_layer(layer: str) -> list[dict]:
    items, token = [], None
    while True:
        q = {"prefix": PREFIX.format(layer=layer), "maxResults": 1000,
             "fields": "items(name,size,md5Hash),nextPageToken"}
        if token:
            q["pageToken"] = token
        url = API.format(bucket=BUCKET, query=urllib.parse.urlencode(q))
        with urllib.request.urlopen(url) as r:
            page = json.load(r)
        items += [i for i in page.get("items", []) if i["name"].endswith(".tif")]
        token = page.get("nextPageToken")
        if not token:
            return items


def chip_event(name: str) -> str:
    """Event (country) of a chip from its file name, e.g. Sri-Lanka_249079_S1Hand.tif."""
    return Path(name).name.split("_")[0]


def chip_id(name: str) -> str:
    """Event and chip number, shared by the layers of one chip: Bolivia_103757."""
    return "_".join(Path(name).name.split("_")[:2])


def fetch(dest: Path | None = None, layers: list[str] = LAYERS, workers: int = 8) -> Path:
    dest = dest or config.path("raw_layers.s1_labels")

    def get(item: dict, layer: str) -> None:
        out = dest / layer / Path(item["name"]).name
        if out.exists() and out.stat().st_size == int(item["size"]):
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".part")
        urllib.request.urlretrieve(DOWNLOAD.format(bucket=BUCKET, name=item["name"]), tmp)
        tmp.rename(out)

    for layer in layers:
        items = list_layer(layer)
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(lambda i, layer=layer: get(i, layer), items))
        log.info("%s: %d chips", layer, len(items))
    return dest


def main(argv: list[str] | None = None) -> None:
    from cri import runlog

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--layers", nargs="*", default=LAYERS)
    a = p.parse_args(argv)
    runlog.setup_logging()
    print(fetch(layers=a.layers))


if __name__ == "__main__":
    main()
