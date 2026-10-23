# IMD best track (RSMC New Delhi)

- **Source:** India Meteorological Department, RSMC New Delhi best-track workbook (currently `Best_Tracks__Data__1982-2026_.xlsx` from rsmcnewdelhi.imd.gov.in). Read through the `imdtrack` package's parsed mirror (`raw.githubusercontent.com/syedhamidali/imdtrack/main/data/*.parquet`), which records the workbook URL and SHA-256 in `manifest.json`.
- **Licence:** IMD does not state terms on the download; treat as public data with attribution to IMD RSMC New Delhi. `imdtrack` code is BSD-3-Clause.
- **Coverage:** 1982-05-01 to 2026-01-10; 425 systems, 7,585 fixes (manifest of 2026-08-09). Bay of Bengal, Arabian Sea and land.
- **Content:** per fix: time (UTC), lat, lon, maximum sustained wind (kt), pressure, pressure drop, Dvorak CI, IMD grade (D, DD, CS, SCS, VSCS, ESCS, SuCS), QC flags `pos_suspect`, `date_suspect`.
- **Obtained by:** `python -m cri.ingest.imd_tracks` (Phase 1F) into `data/raw/imd/`; the manifest is saved with it.
- **Known problems:** fixes are 3-hourly in recent years and sparser earlier; no wind radii, so footprints use distance to track; the mirror is a third-party parse, so compare a few storms against the IMD workbook (Phase 1F).
- **Used for:** cyclone footprints per district (Phase 1F), landfall frequency (Phase 1H), cyclone indicators (Phase 2A), the event generator (Phase 4C).
