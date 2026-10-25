# EM-DAT

- **Source:** CRED, UCLouvain, EM-DAT international disaster database (public.emdat.be).
- **Licence:** free for non-commercial use after registration; the raw data may not be redistributed (see doc.emdat.be/docs/data-accessibility/).
- **Status:** downloaded 2026-10-25 by Aradhya: India, 2000 to 2026, 436 rows of every disaster type (209 floods, 111 storms and 3 glacial lake outburst floods; the other types are ignored). Saved as `data/raw/emdat/emdat_india_2026-10-25.xlsx` on each machine; never committed.
- **Known problems:** many entries list only a state or a free-text location; damages are estimates; one record often covers a whole monsoon season in several states, with combined deaths and damage; inclusion thresholds (10 deaths, 100 affected, emergency declaration or appeal) drop small events.
- **Processing (`cri.ingest.emdat`):**
  - keeps ISO IND; floods of every subtype and glacial lake outburst floods; storms only when the subtype is Tropical cyclone (64 thunderstorm, lightning, hail, dust, tornado, winter and "severe weather" storms are dropped);
  - partial dates are filled to the first or last day of the month or year and flagged in `date_precision`;
  - location from `GADM Admin Units` (gid/name JSON), else the deprecated `Admin Units`, else free-text `Location`. A GADM district's state comes from its gid (GADM files Indian Kashmir under `Z01.14`, whose state is inferred from its district names), and states that only the `Location` text names are added;
  - district names are matched within their own state, then the record's states, then across India; names of districts renamed or carved out after 2011 map to their Census 2011 district through `configs/district_aliases.yaml`, which also maps Telangana to Andhra Pradesh and Ladakh to Jammu & Kashmir;
  - every non-exact match goes to `data/interim/emdat_geocode_review.csv`;
  - `geo_level` is the level of each row (district, state, or country when a record has no usable place); `record_level` is the finest level the record reaches, so `record_level = state` flags a record that lists only states;
  - each record is linked to an IMD storm (by name, else by dates) and to the GFD event with the largest date overlap.
- **Result of the 2026-10-25 export:** 259 records kept (212 floods, 47 cyclones). 158 reach district level (136 floods, 22 cyclones), 99 list only states and 2 have no usable place. 405 distinct districts are named. 7 names stay unmatched and none is a usable district name: "Administrative unit not available", "Cachemire" (French for Kashmir), "Bengal" (twice), "Meghalaya Nagaland", "Sikkim Gangtok", and "Barpet distrcits" (a typo for Barpeta, which the same record already reaches through Bajali).
- **Output:** `data/processed/disaster_records.parquet`, one row per record and district (or state). The event catalogue (`cri.events.catalogue`) adds the matching DisNo. to `events.emdat_id` and writes the EM-DAT dates, deaths, people affected and damage of each event to `data/processed/event_emdat.parquet`.
- **Used for:** event dates and impacts (Phase 1G), validation of the hazard score at state level (Phase 2C, `docs/hazard_validation.md` section 3). Only derived counts, correlations and record ids are published.
