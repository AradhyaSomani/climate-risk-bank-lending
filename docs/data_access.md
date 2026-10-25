# Data access

No raw data is in Git. Each dataset below is either fetched by the pipeline itself (no
account needed) or has to be downloaded by hand because its terms forbid redistribution or
need a login. The data cards in `docs/data_cards/` hold the full source, licence and known
problems for each one.

Checksums of the raw files as downloaded for this project are in
[`raw_checksums.sha256`](raw_checksums.sha256) (`sha256sum` format). After downloading:

```bash
python scripts/raw_checksums.py --check     # or: sha256sum -c docs/raw_checksums.sha256
```

A file that differs means the provider has changed it since; record the new version in the
decision log before rebuilding. Remote sources read in place (cloud-optimised tiles) have no
local file to check; their version is pinned in the config named below.

## Fetched by the pipeline (public, no account)

| Dataset | Licence | Fetched by | Lands in |
|---|---|---|---|
| Census 2011 district boundaries (DataMeet) | CC BY 4.0 | `cri.geo.districts` on first use | `data/raw/districts/` |
| Natural Earth land and rivers (10 m) | public domain | `cri.geo.land` on first use | `data/raw/natural_earth/` |
| IMD RSMC best tracks, 1982 onward | public, attribute IMD | `python -m cri.ingest.imd_tracks` | `data/raw/imd/` (with `manifest.json` holding the source SHA-256) |
| Global Flood Database v1 (`gs://gfd_v1_4`) | CC BY-NC 4.0 | `python -m cri.ingest.gfd index`, then `make hazard` | event zips are reduced to `data/interim/flood_extent/` and the grids in `data/interim/gfd_grid_0.02/` |
| JRC Global Surface Water 1.4 | free, cite Pekel et al. 2016 | read in place by `cri.hazard.baseline` | `data/interim/baseline_rasters_*.parquet` |
| Copernicus DEM GLO-90 (AWS) | Copernicus DEM licence, attribution required | read in place by `cri.hazard.baseline` | same |
| ESA WorldCover 2021 | CC BY 4.0 | read in place by `cri.hazard.landcover` | used on the fly (flooded built-up and crop shares, susceptibility features) |
| Sen1Floods11 v1.1 hand-labelled chips | not stated: research use, **do not redistribute** | `python -m cri.ingest.sen1floods11` | `data/raw/s1_labels/` (446 chips x 3 layers) |

## Needs an account or a manual download

| Dataset | Why manual | Steps |
|---|---|---|
| EM-DAT (CRED) | free registration; raw data may not be redistributed | Register at public.emdat.be, filter Country = India, Disaster type = Flood and Storm, all years; export xlsx to `data/raw/emdat/`. Then `python -m cri.ingest.emdat data/raw/emdat/<file>.xlsx`. |
| Sentinel-1 GRD scenes (Kerala 2018 and other events) | Earth Engine account | `pip install -e ".[gee]"`, `earthengine authenticate`, then `python -m cri.ingest.sentinel1 --kind backscatter ...` (see the Sentinel-1 data card). |
| RBI district credit and deposits (DBIE) | browser download (DBIE may ask for a captcha; RBI terms grant no reuse licence) | Follow the steps in `docs/data_cards/rbi.md` into `data/raw/rbi/`, then `python scripts/rbi_first_look.py`. |

## What is not redistributed in a release

GFD-derived tables carry the CC BY-NC 4.0 condition, so any release that includes the
hazard scores is non-commercial. EM-DAT rows, Sen1Floods11 chips and the raw RBI files are
never published; only tables and aggregates derived from them (validation numbers, model
metrics, the district panel with its RBI source line) are.

## Running without any data

Every contract has a toy sample in `tests/fixtures/contracts/`. The API runs on them:

```bash
make api-sample        # CRI_API_SOURCE=sample uvicorn cri.api.app:app
```
