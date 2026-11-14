# Copernicus DEM GLO-90

- **Source:** ESA Copernicus DEM, AWS open data bucket `copernicus-dem-90m` (1x1 degree COGs).
- **Licence:** free for any use under the Copernicus DEM licence; attribution "produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA".
- **Coverage:** global, 90 m (3 arc-seconds).
- **Used for:** elevation, slope and a height-above-nearest-drainage proxy (Phase 1H, 2B-C). MERIT Hydro's HAND band is an alternative through Earth Engine but its licence (CC BY-NC 4.0 or ODbL) needs checking first.
- **Processing (`cri.hazard.baseline`):** tiles read from their internal overviews and averaged onto a 0.005-degree India grid (about 500 m); per district: mean elevation, mean slope (latitude-corrected spacing), share below 10 m, and `rel_elev_median_m`, the median height above the district's 5th-percentile elevation. That last one is a **proxy** for height above nearest drainage, not HAND itself.
- **Earth Engine copy (Sentinel-1 slope mask only):** `cri.ingest.sentinel1` reads the 30 m GLO-30 collection `COPERNICUS/DEM/GLO30_2024_1` (band `DEM`) to mask slopes above 5 degrees. It replaced `COPERNICUS/DEM/GLO30`, which Earth Engine marked deprecated; the first three Sentinel-1 exports (13 November 2026) still used the old collection. The baseline indicators above use GLO-90 from AWS and are not affected.
