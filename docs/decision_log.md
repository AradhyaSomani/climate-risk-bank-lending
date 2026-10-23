# Decision log


## 2026-10-23 Phase 0A hazard data check (A)

- **Kerala 2018 has no Global Flood Database footprint** (GFD v1 has no India event in mid-August 2018). Decision: the Kerala extent comes from Sentinel-1 (Otsu baseline first, U-Net if it passes its gate). The GFD-versus-Sentinel-1 agreement check in Phase 1E moves to Chennai 2015 (DFO 4309). Needs B's agreement because Kerala is the anchor case of Phase 3H.
- Uttarakhand 2013 is also missing from GFD; it stays in the candidate list as unverified and will probably drop.
- GFD event rasters are 250 m (0.002246°), not 30 m; areas use per-pixel geodesic area.
- Sen1Floods11's official splits are random within events; Phase 2B-B uses leave-one-event-out splits and holds India out for the cross-domain check.
- Earth Engine is needed only for Sentinel-1; every other hazard layer is fetched as files from public buckets.
- Provisional district geometry: DataMeet Census 2011 districts (CC BY 4.0) until B's district master (C1) is built; same Census 2011 codes.
