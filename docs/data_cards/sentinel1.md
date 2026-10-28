# Sentinel-1 GRD

- **Source:** ESA Copernicus Sentinel-1 C-band SAR, Interferometric Wide swath GRD. Earth Engine `COPERNICUS/S1_GRD` (calibrated, terrain-corrected backscatter in dB).
- **Licence:** Copernicus Sentinel data terms: free and open, attribution "Contains modified Copernicus Sentinel data [year]".
- **Coverage:** October 2014 onwards (Sentinel-1B lost December 2021, so 12-day revisit until Sentinel-1C in 2025).
- **Obtained by:** Earth Engine export to Google Drive (`python -m cri.ingest.sentinel1 --event <event_id> --project <cloud project>`, needs `.[gee]` and a noncommercial Earth Engine project, which needs no billing). Dates, orbit and area per event are presets in `configs/hazard.yaml` (`sentinel1`). The GeoTIFFs go in `data/raw/sentinel1/` as Earth Engine names them (`FL-2018-KERALA_s1_otsu.tif`, or several `...-0000000000-0000000000.tif` parts for a large export); `python -m cri.hazard.flood_extent --s1` (also run by `make hazard`) turns them into district rows. The AWS copy is requester-pays and is not used.
- **Exports so far:** none.
- **Known problems:** needs a pre-event reference scene from the same orbit; urban double-bounce and dense vegetation hide water; wind roughens water surfaces.
- **Used for:** Kerala 2018 extent (GFD has none) and every post-2018 flood (Phase 1E, 2B-B).
