# Phase 0A: hazard data reality check (Person A)

Checked 2026-10-23 by downloading from each source, not from documentation alone. The RBI
panel check is Person B's (`docs/00_rbi_audit.md`).

## Summary

| Layer | Access tested | Coverage | Resolution | Licence | Verdict |
| --- | --- | --- | --- | --- | --- |
| Global Flood Database v1 | Yes: public bucket `gfd_v1_4`, all 913 event properties read | 2000-02-17 to 2018-12-10; **147 events with flood water in India** | 0.002246° (about 250 m) | CC BY-NC 4.0 | Usable for pre-2019 floods. **Kerala 2018 is not in it** |
| IMD best track (RSMC New Delhi) | Yes: parsed parquet mirror of the IMD workbook via `imdtrack` | 1982-05 to 2026-01, 425 systems, 7,585 fixes | 3-hourly fixes (some 6-hourly) | IMD data: terms not stated, cite RSMC New Delhi; `imdtrack` code BSD-3 | Usable now for every cyclone candidate |
| Sen1Floods11 v1.1 | Yes: public bucket `sen1floods11`, metadata and split files read | 11 events 2016-2019, 446 hand-labelled 512x512 chips at 10 m, 68 of them India (2016-08-12) | 10 m | STAC says "proprietary"; no licence file | Usable for research with citation; do not redistribute chips |
| Sentinel-1 GRD | Earth Engine `COPERNICUS/S1_GRD` only (AWS bucket is requester-pays) | 2014-10 onwards | 10 m | Copernicus open licence | Needs an Earth Engine account for Kerala 2018 and post-2018 events |
| JRC Global Surface Water 1.4 | Yes: public bucket `global-surface-water`, occurrence tile 70E_10N | 1984-2021 | 30 m | Copernicus: free, no restriction, cite | Usable for permanent water |
| Copernicus DEM GLO-90 | Yes: AWS open data `copernicus-dem-90m` | Global | 90 m | Copernicus DEM licence (free, attribution) | Usable for elevation, slope and a HAND proxy |
| ESA WorldCover 2021 | Yes: AWS open data `esa-worldcover` | 2020 and 2021 maps | 10 m | CC BY 4.0 | Usable for built-up and cropland masks |
| EM-DAT | No: needs a registered account | 1900 onwards | Event, admin units | Free non-commercial, no redistribution of the raw file | Needs the user to register and download |
| NRSC flood hazard atlas | No download route found | Bihar complete; Odisha, West Bengal, Uttar Pradesh in progress | District | Not stated | Validation only, if obtained |
| District boundaries (DataMeet Census 2011) | Yes: `datameet/maps`, 641 polygons, Census 2011 codes | All of India, 2011 | Vector | CC BY 4.0 | Usable as the geometry until B's `district_master` (C1) lands |

## Findings that change the plan

1. **The anchor event has no Global Flood Database footprint.** GFD v1 has no India record
   for August 2018 (the nearest are DFO 4665, 2-10 August in Assam, and DFO 4673, 1-7
   September in north India). The task list assumes GFD covers Kerala 2018 and Sentinel-1 is
   only a cross-check. In practice the Kerala footprint must come from Sentinel-1 (the Otsu
   baseline first, the U-Net if it passes its gate), and the GFD-versus-Sentinel-1 comparison
   in Phase 1E has to use a different event (Chennai 2015 is the best overlap; Sentinel-1 is
   available from late 2014). Recorded in `docs/decision_log.md`.
2. **Uttarakhand 2013 is not in GFD either**, and narrow valley floods are below MODIS
   resolution. It needs a different footprint (EM-DAT district list, or drop it).
3. **GFD resolution is 250 m**, not 30 m: the event GeoTIFFs have a pixel of 0.002246°.
   Only the `jrc_perm_water` band is 30 m data resampled onto the same grid. Areas must be
   computed with per-pixel area at that latitude, not a fixed 30 m cell.
4. **GFD events are multi-country and long.** Many India records span India, Nepal and
   Bangladesh for weeks (for example DFO 3365, the 2008 Kosi event, runs 18 August to 24
   September). The per-event flooded share is a maximum extent over that window, so the
   impact quarter is set from the start date, not the end.
5. **Sen1Floods11's official split is random**, 60-20-20 by chip within events, with only
   Bolivia held out. That breaks the split-by-region rule, so Phase 2B-B builds its own
   leave-one-event-out splits and keeps India out of training for the cross-domain check.
6. **The IMD best track is complete and current** (to January 2026), so cyclone footprints do
   not need EM-DAT and can be built now. Grades follow IMD classes D to SuCS.
7. **Earth Engine is only needed for Sentinel-1.** GFD, JRC water, DEM and land cover are all
   reachable as files, so `make hazard` can run without an Earth Engine account apart from
   the Sentinel-1 step.

## Candidate events checked against the data

`data/events/events_candidates.csv` lists the 15 candidate events from the task list with the
matching GFD event id and IMD storm id. Cyclone dates are the first and last best-track fix;
flood dates are the GFD window. Two remain unverified (Kerala 2018, Uttarakhand 2013) because
neither source covers them; both need EM-DAT. Treated-district counts and the power check
are filled in once footprints exist (Phase 1E, 1F) and are Person B's call.

## How to reproduce

```bash
python -m cri.ingest.gfd index --out data/raw/gfd/gfd_events.csv \
       --india-out data/events/gfd_india_events.csv
```

`data/events/gfd_india_events.csv` is the result (147 events; GFD metadata, CC BY-NC 4.0).
