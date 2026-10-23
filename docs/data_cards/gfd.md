# Global Flood Database v1

- **Source:** Tellman et al. (2021), *Satellites observe increasing proportion of population exposed to floods*, Nature, doi:10.1038/s41586-021-03695-w. Earth Engine `GLOBAL_FLOOD_DB/MODIS_EVENTS/V1`; also one zip per event in the public bucket `gs://gfd_v1_4` (used here, no account needed).
- **Licence:** CC BY-NC 4.0 (licence file inside every zip). Non-commercial use with attribution.
- **Coverage:** 913 events, 2000-02-17 to 2018-12-10; 147 have flood water in India (`cc` contains IND).
- **Content:** GeoTIFF bands `flooded` (0/1 maximum extent), `duration` (days), `clear_views`, `clear_perc`, `jrc_perm_water`; float32; EPSG:4326; pixel 0.002246° (about 250 m). Properties JSON per event: DFO id, began/ended, countries, cause, dead, displaced, severity, centroid.
- **Obtained by:** `python -m cri.ingest.gfd index` then `python -m cri.ingest.gfd fetch <dfo_id>` into `data/raw/gfd/`.
- **Known problems:** MODIS misses short floods and flooding under cloud (check `clear_perc`); events are long multi-country windows; urban and narrow-valley floods are under-detected; the record ends in 2018 and has **no Kerala 2018 or Uttarakhand 2013 event**; the Earth Engine catalog lists 30 m but the event rasters are 250 m.
- **Used for:** per-event flooded share by district (Phase 1E), long-run flood frequency (Phase 1H), flood indicators (Phase 2A), susceptibility labels (Phase 2B-C).
