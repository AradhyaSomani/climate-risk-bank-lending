# Sentinel-1 GRD

- **Source:** ESA Copernicus Sentinel-1 C-band SAR, Interferometric Wide swath GRD. Earth Engine `COPERNICUS/S1_GRD` (calibrated, terrain-corrected backscatter in dB).
- **Licence:** Copernicus Sentinel data terms: free and open, attribution "Contains modified Copernicus Sentinel data [year]".
- **Coverage:** October 2014 onwards (Sentinel-1B lost December 2021, so 12-day revisit until Sentinel-1C in 2025).
- **Obtained by:** Earth Engine export (`python -m cri.ingest.sentinel1`, needs `.[gee]` and an authenticated account). The AWS copy is requester-pays and is not used.
- **Known problems:** needs a pre-event reference scene from the same orbit; urban double-bounce and dense vegetation hide water; wind roughens water surfaces.
- **Used for:** Kerala 2018 extent (GFD has none) and every post-2018 flood (Phase 1E, 2B-B).
