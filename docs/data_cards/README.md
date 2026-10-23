# Data cards

One card per dataset: source, licence, coverage, how it is obtained, known problems and how the
project uses it. Person A's hazard layers are below; RBI and census cards are Person B's.

## What may be published

| Dataset | Raw file in the repo or release | Derived district tables |
| --- | --- | --- |
| Global Flood Database | No (rebuild instructions only) | Yes, non-commercial, with attribution (CC BY-NC 4.0 carries over) |
| IMD best track | No | Yes, with attribution to RSMC New Delhi |
| Sen1Floods11 | No | Model weights and scores only, with citation |
| Sentinel-1 | No | Yes |
| JRC Global Surface Water | No (large) | Yes |
| Copernicus DEM GLO-90 | No (large) | Yes, with the Copernicus attribution |
| ESA WorldCover | No (large) | Yes (CC BY 4.0) |
| EM-DAT | **Never** | Counts and flags only, no row-level copy of EM-DAT fields |
| DataMeet district boundaries | No (B owns `district_master`) | Yes (CC BY 4.0) |
| Natural Earth land | No | Yes (public domain) |

Because the GFD licence is non-commercial, any release that includes GFD-derived scores is
non-commercial too. Code is licensed separately (decided in Phase 5E).

| Card | Dataset |
| --- | --- |
| [gfd.md](gfd.md) | Global Flood Database v1 |
| [imd_best_track.md](imd_best_track.md) | IMD RSMC New Delhi best track |
| [sen1floods11.md](sen1floods11.md) | Sen1Floods11 labelled flood chips |
| [sentinel1.md](sentinel1.md) | Sentinel-1 GRD |
| [jrc_gsw.md](jrc_gsw.md) | JRC Global Surface Water |
| [copernicus_dem.md](copernicus_dem.md) | Copernicus DEM GLO-90 |
| [esa_worldcover.md](esa_worldcover.md) | ESA WorldCover |
| [emdat.md](emdat.md) | EM-DAT |
| [district_boundaries.md](district_boundaries.md) | DataMeet Census 2011 districts |
| [natural_earth.md](natural_earth.md) | Natural Earth 10 m land |
