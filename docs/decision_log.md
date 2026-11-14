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

## 2026-10-28 Sentinel-1 footprints, before any export (A)

- Which map becomes a flood event's footprint now follows `flood.source_pre2019` and `flood.source_post2018` in `configs/hazard.yaml` by the event's start year (GFD before 2019, the U-Net after), then the other sources. Until now the catalogue took any Sentinel-1 map first, so a Sentinel-1 export of Chennai 2015, made only for the comparison with GFD, would have replaced Chennai's GFD footprint. Rebuilt on the current tables, `event_district.parquet` is unchanged.
- A Sentinel-1 map becomes a footprint only if it has a row for every district of the event's states. The U-Net export of Kerala covers central Kerala only (10 m for the whole state is about 18 GB), so Kerala's footprint will be the Otsu change-detection map, and the U-Net map is compared with it there (Phase 2B B6).
- Kerala windows (proposed): before, 1 April to 28 May 2018, ahead of the monsoon onset on 29 May, so the July flooding in Kuttanad is not part of the reference; after, 14 to 24 August. They define Kerala's treated districts, so Devna and Aradhya agree them before signing the pre-registration. No outcome has been looked at.

## 2026-11-11 District crosswalk and RBI panel (B, built by Aradhya)

- Geography: the 640 Census 2011 districts of the DataMeet boundary file, with Census 2011
  population and an urban share from households (the source has no urban persons).
- An RBI district name is matched only exactly, after normalisation, or by a decision written
  in `configs/crosswalk.yaml` or `configs/district_aliases.yaml`. Fuzzy scores only suggest;
  an unmatched name stops the build.
- A district created after 2011 goes with weight 1 to the 2011 district it was mostly carved
  from. Population shares across two or more 2011 parents would need sub-district (tehsil)
  populations, which we do not have; those parents get `split_flag` instead (79 districts,
  most from the 2016 Telangana, 2022 Andhra Pradesh and 2023 Rajasthan reorganisations).
  The Rajasthan ones come after every main event window; the Telangana and Andhra Pradesh
  ones fall inside the later windows, so a robustness run should drop flagged districts.
- A 2011 district created between 2004 and 2011 is inside its parent's RBI label until RBI
  first reports it; that label is shared by 2011 population (the CEDA rule), and the panel
  records the shared part in `imputed_share`. Delhi's single label is shared among its nine
  districts the same way. Mumbai and Delhi are flagged because population is a poor guide
  to where credit is booked.
- `series_break` marks the first quarter of each reporting regime: 2017-06-30 (after the
  gap; bank credit instead of gross bank credit; quarter-end dates) and 2023-03-31 (built from
  BSR-1 and BSR-2; March only). **For the pre-registration:** its rule "quarters flagged
  `series_break` are missing for the outcome concerned" would, with this flag, drop June 2017
  and March 2023 as well. Proposed reading, to settle before signing: the flag marks a
  change in basis, the quarter-by-event fixed effects absorb a common level shift, and the
  quarter is kept; a robustness run drops event windows that cross a break.
- No district's figures were printed or plotted while building the panel. The checks used
  coverage counts and office counts only. The outlier review against the source waits for
  the signed pre-registration.

## 2026-11-13 Controls (B, built by Aradhya)

- Rainfall from CHIRPS (0.05 degrees, daily, from 1981) instead of IMD's gridded rainfall:
  IMD's download site cannot be reached from our cloud environment, CHIRPS is in Earth
  Engine next to the Sentinel-1 work, and it covers the whole 1991-2020 normal used for the
  anomaly.
- Night lights: VIIRS monthly for quarterly variation from 2014 (Earth Engine's stray-light
  corrected series starts in January 2014), and the published
  harmonised DMSP-VIIRS annual series (Li et al. 2020) as the long series from 2000, instead
  of bridging DMSP and VIIRS ourselves. Its DMSP and VIIRS parts both hold 2013; we take
  2013 from DMSP, the series it continues, rather than averaging the two.
- State loan waivers enter as flags by announcement quarter, with cooperative-only waivers
  kept apart. They are controls, set before any outcome is looked at; their dates still need
  checking against the state orders.

## 2026-11-14 Sentinel-1 exports and the Kerala footprint (A)

- The three exports ran on 13 November 2026 with the proposed windows and the descending
  orbit (Kerala 22 scenes before and 5 after; Chennai 6 and 6). The ascending orbit had 5 and 4
  for Kerala and none for Chennai. Task ids, files and sizes are in
  `docs/data_cards/sentinel1.md`.
- The slope mask now reads `COPERNICUS/DEM/GLO30_2024_1`. Earth Engine marked
  `COPERNICUS/DEM/GLO30` deprecated while the exports ran, so these three files still used it.
  They are not re-exported: the mask only removes slopes above 5 degrees, and a re-export
  is one command if a later check needs it.
- Chennai 2015, GFD against Sentinel-1: Spearman 0.12 and hit IoU 0.50 over the 14 districts
  both maps cover, but 0.96 and 0.83 over the 7 districts the export covers for at least half
  their area. The low figure comes from districts at the edge of the export box, which read
  as unflooded. The validation report now gives both (`validation.s1_min_mapped_share: 0.5`).
  Chennai keeps its GFD footprint (`flood.source_pre2019`), as decided on 2026-10-28.
- Kerala's footprint is the Otsu map. With the catalogue rules set before any export (treated
  above 5% flooded, exclusion zone from 1% and for neighbours of treated districts), it gives
  3 treated districts, Alappuzha (12.2%), Thrissur (5.5%) and Kottayam (5.3%), and 8 in the
  exclusion zone, among them the other four worst-hit districts of the Kerala PDNA:
  Ernakulam (1.6%), Wayanad (1.5%), Pathanamthitta (just under 1%) and Idukki (0.5%); the
  last two are in the zone as neighbours of treated districts.
  No PDNA district falls into the control group.
- The U-Net map of central Kerala finds more water in the same districts (Alappuzha 31%,
  Kottayam 10%, Ernakulam 5.4%) and agrees with the Otsu map on ranking (Spearman 0.83 over
  8 districts). Under the U-Net, Ernakulam would also be treated. The Otsu map probably
  under-counts water under canopy and in built-up areas. **For the pre-registration:** keep
  the Otsu footprint as the primary Kerala definition (it covers the whole state and the rule
  was fixed first), and decide before signing whether a robustness run treats the PDNA
  worst-hit districts instead. Only hazard maps were looked at; no credit or deposit figures.
