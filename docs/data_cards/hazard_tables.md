# Person A's processed hazard tables

All in `data/processed/` (DVC, not Git). Contract columns are in `docs/contracts/C3_hazard_tables.yaml`.

| File | Grain | Built by | Source data |
| --- | --- | --- | --- |
| `flood_extent_district_event.parquet` | event x district x source | `cri.hazard.flood_extent` | GFD v1 (pre-2019); Sentinel-1 once exported |
| `cyclone_exposure_district_event.parquet` | storm x district (within 500 km) | `cri.hazard.cyclone_footprint` | IMD best track 1982-2026 |
| `cyclone_storms.parquet` | storm | `cri.hazard.cyclone_footprint` | IMD best track |
| `hazard_baseline_district.parquet` | district | `cri.hazard.baseline` | GFD, JRC GSW, Copernicus DEM, IMD |
| `disaster_records.parquet` | EM-DAT record x district (or state) | `cri.ingest.emdat` | EM-DAT (not yet downloaded) |

## Conventions

- District id: Census 2011 code (640 districts); geometry from B's master or DataMeet.
- Event ids: `GFD-<dfo id>` for flood database events, `IMD-<year>-<serial>` for storms. The
  Phase 3A catalogue maps these to the project's named events (`FL-2018-KERALA`, ...).
- Times are UTC. Areas in km2 from exact spherical pixel areas (rasters) or an Albers
  equal-area projection (polygons). Distances in km in EPSG:7755.
- Every number that depends on a threshold reads it from `configs/hazard.yaml`; those values
  are placeholders until the pre-registration fixes them.

## Known problems

- GFD under-detects urban and short floods and has no Kerala 2018 or Uttarakhand 2013 event.
- `flooded_share` is relative to the whole district; `mapped_share` says how much of the
  district the event raster observed. A district with `mapped_share` near 0 is unobserved,
  not dry.
- GFD windows can overlap in time, so `gfd_pixel_flood_count` can count one flood twice when
  two overlapping records cover the same place.
- Cyclone exposure is distance-and-grade only (no wind radii in the IMD record).
- `rel_elev_median_m` is a proxy for height above nearest drainage, not HAND.
- Coverage by state: `docs/eval_reports/hazard_coverage.md`.

## Not done yet

- Tag `data-v1`: waits for the Phase 1 gate, when B's district master, crosswalk and panel
  exist and `make data` rebuilds everything from raw.
