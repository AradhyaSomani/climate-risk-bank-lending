# Decision log


## 2026-10-23 Phase 0A hazard data check (A)

- **Kerala 2018 has no Global Flood Database footprint** (GFD v1 has no India event in mid-August 2018). Decision: the Kerala extent comes from Sentinel-1 (Otsu baseline first, U-Net if it passes its gate). The GFD-versus-Sentinel-1 agreement check in Phase 1E moves to Chennai 2015 (DFO 4309). Needs B's agreement because Kerala is the anchor case of Phase 3H.
- Uttarakhand 2013 is also missing from GFD; it stays in the candidate list as unverified and will probably drop.
- GFD event rasters are 250 m (0.002246°), not 30 m; areas use per-pixel geodesic area.
- Sen1Floods11's official splits are random within events; Phase 2B-B uses leave-one-event-out splits and holds India out for the cross-domain check.
- Earth Engine is needed only for Sentinel-1; every other hazard layer is fetched as files from public buckets.
- Provisional district geometry: DataMeet Census 2011 districts (CC BY 4.0) until B's district master (C1) is built; same Census 2011 codes.

## 2026-10-25 EM-DAT records (A)

- EM-DAT export of 25 October 2026 (India, floods and storms, 2000 to 2026) ingested. Storms are kept only when the subtype is Tropical cyclone; the other 64 (thunderstorms and lightning, "severe weather", general storms, hail, dust storms, tornadoes and winter storms) are dropped.
- District names that changed after 2011, and districts carved out after 2011, map to their Census 2011 district through `configs/district_aliases.yaml` (a new district goes to the district it was carved from). Telangana maps to Andhra Pradesh and Ladakh to Jammu & Kashmir.
- Kerala 2018 and Uttarakhand 2013 dates checked against EM-DAT and kept: the press-report windows sit inside the EM-DAT records, so neither impact quarter moves. Both EM-DAT records cover several states at once.
- An EM-DAT record belongs to a catalogue event when it has the same hazard type, shares a state, and either carries the event's IMD storm id or overlaps its dates within 3 days (`emdat_slack_days` in `configs/events.yaml`). Every one of the 15 events gets exactly one record.

## 2026-10-25 U-Net leakage check (A)

- The shuffled-label check (Evaluation B5) was run twice. Seed 7 collapsed (test IoU 0.072, all-water 0.142). Seed 42 did not under the rule set before the run (0.261 against a threshold of 0.192).
- Decided **after seeing the seed-42 result**: a shuffled run also counts as showing no leak when it stays below Otsu on VH per chip (0.324), a method that uses no labels. Reason: the held-out events never reach training or epoch selection, so the remaining score can only come from the input (dark radar returns are water), not from the labels. The U-Net stays kept; its card reports both runs and both criteria.

## 2026-10-25 RBI quarters that are not available (A)

- September 2016, December 2016 and March 2017 (the first BSR-7 entry's district statement stops at June 2016) and the June, September and December quarters from 2023 need a DBIE login to download, and DBIE has no sign-up. Decision (Aradhya): exclude them; the panel has a gap from June 2016 to June 2017 and only March figures from 2023. March 2017 from the annual volume is not spliced in, because it is on another basis.
- Consequence: Chennai 2015 lacks quarters +3 to +5. Whether it is dropped or the completeness rule is relaxed is open in `docs/00_hypotheses.md` until Devna and Aradhya sign. Amphan's last quarter (June 2023) is missing too, after quarter +3.
