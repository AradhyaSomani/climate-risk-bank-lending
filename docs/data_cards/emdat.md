# EM-DAT

- **Source:** CRED, UCLouvain, EM-DAT international disaster database (public.emdat.be).
- **Licence:** free for non-commercial use after registration; the raw data may not be redistributed (see doc.emdat.be/docs/data-accessibility/).
- **Status:** not downloaded. Needs Aradhya to register and export India floods and storms (all years) as xlsx into `data/raw/emdat/`.
- **Known problems:** many entries list only a state or a free-text location; damages are estimates; inclusion thresholds (10 deaths, 100 affected, emergency declaration or appeal) drop small events.
- **Processing (`cri.ingest.emdat`):** keeps ISO IND, types Flood and Storm; partial dates are filled to the first or last day of the month or year and flagged in `date_precision`; location from `GADM Admin Units` (gid/name JSON), else the deprecated `Admin Units`, else free-text `Location`; district names matched within the record's states (exact, then normalised, then fuzzy at 0.85), every non-exact match written to `data/interim/emdat_geocode_review.csv`; records naming only a state are kept with `geo_level = state`; each record is linked to an IMD storm (by name, else by dates) and to the GFD event with the largest date overlap.
- **Output:** `data/processed/disaster_records.parquet`, one row per record and district (or state).
- **Used for:** event dates and impacts (Phase 1G), validation of the hazard score at state level (Phase 2C). Only derived counts and flags are published.
