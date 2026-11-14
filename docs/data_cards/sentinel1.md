# Sentinel-1 GRD

- **Source:** ESA Copernicus Sentinel-1 C-band SAR, Interferometric Wide swath GRD. Earth Engine `COPERNICUS/S1_GRD` (calibrated, terrain-corrected backscatter in dB).
- **Licence:** Copernicus Sentinel data terms: free and open, attribution "Contains modified Copernicus Sentinel data [year]".
- **Coverage:** October 2014 onwards (Sentinel-1B lost December 2021, so 12-day revisit until Sentinel-1C in 2025).
- **Obtained by:** Earth Engine export to Google Drive (`python -m cri.ingest.sentinel1 --event <event_id> --project <cloud project>`, needs `.[gee]` and a noncommercial Earth Engine project, which needs no billing). Dates, orbit and area per event are presets in `configs/hazard.yaml` (`sentinel1`). The GeoTIFFs go in `data/raw/sentinel1/` as Earth Engine names them (`FL-2018-KERALA_s1_otsu.tif`, or several `...-0000000000-0000000000.tif` parts for a large export); `python -m cri.hazard.flood_extent --s1` (also run by `make hazard`) turns them into district rows. The AWS copy is requester-pays and is not used.
- **Exports so far:** three, made on 13 November 2026 from the noncommercial Earth Engine project `cri-earth-engine` into the Drive folder `cri-sentinel1`, each as a single file. Scene counts from `--check` (before / after window):

  | File | Earth Engine task | Area | Orbit | Scenes | Pixel | Size |
  | --- | --- | --- | --- | --- | --- | --- |
  | `FL-2018-KERALA_s1_otsu.tif` | XPCVI4HFSQOCN7VWDVQKRD2Q | Kerala | descending | 22 / 5 | 30 m | 2.0 MB |
  | `FL-2018-KERALA_s1_backscatter.tif` | EBREFPICNNHQEWDXLSLWRQ2O | central Kerala, bbox 76.2 9.0 76.9 10.3 | descending | after only: 5 | 10 m | 883 MB |
  | `FL-2015-CHENNAI_s1_otsu.tif` | 6L3ZVKNE47ROUZYQQIHAPOL6 | bbox 79.0 11.4 80.4 14.0 | descending | 6 / 6 | 30 m | 2.2 MB |

  Windows are the presets in `configs/hazard.yaml`: Kerala before 1 April to 28 May 2018, after 14 to 24 August 2018; Chennai before 1 August to 15 October 2015, after 10 November to 10 December 2015. The ascending orbit had 5 / 4 scenes for Kerala and none for Chennai, so both use descending. The two flood maps' slope mask used `COPERNICUS/DEM/GLO30`, which Earth Engine has since marked deprecated; the code now uses `COPERNICUS/DEM/GLO30_2024_1` (see the Copernicus DEM card). The files have not been re-exported, so a new export may differ slightly where the slope mask changes. The files are in DVC under `data/raw/sentinel1/`.
- **District rows (`flood_extent_district_event.parquet`):** Kerala `s1_otsu` 33 districts (every Kerala district fully mapped, plus edge districts of neighbouring states with partial cover), Kerala `s1_unet` 8 districts of central Kerala, Chennai `s1_otsu` 14 districts, 5 of them under 20% mapped. Kerala's footprint is the `s1_otsu` map; Chennai keeps its GFD footprint. Agreement with the other maps is in `docs/hazard_validation.md` section 5.
- **Known problems:** needs a pre-event reference scene from the same orbit; urban double-bounce and dense vegetation hide water; wind roughens water surfaces.
- **Used for:** Kerala 2018 extent (GFD has none) and every post-2018 flood (Phase 1E, 2B-B).
