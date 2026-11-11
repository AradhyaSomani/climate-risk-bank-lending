# Census 2011 district table

- **What:** one row per Census 2011 district (640) with population, workers by category,
  households by rural and urban residence, religion, education and household assets, keyed
  by the Census 2011 district code.
- **File:** `data/raw/census2011/india-districts-census-2011.csv`, fetched with
  `python -m cri.geo.district_master fetch` on 2026-11-11 by Aradhya Somani. Checksum in
  `docs/raw_checksums.sha256`.
- **Source:** the Kaggle dataset "India Census 2011" (compiled from the Census of India 2011
  Primary Census Abstract and Houselisting tables), as mirrored in the GitHub repository
  `nishusharma1608/India-Census-2011-Analysis` (raw.githubusercontent.com is reachable from
  our cloud environment; censusindia.gov.in is not). The underlying figures are the Census
  of India's published tables.
- **Licence:** the mirror states none, and the Kaggle page could not be opened from here.
  Census of India tables are public government statistics. We publish only derived columns
  (population and urban share per district, in `district_master.parquet`) and cite the
  Census of India 2011. Check the Kaggle page's licence before any release.
- **Checks done:** 640 rows, codes 1 to 640, every code matches the DataMeet boundary file's
  `censuscode` (`tests/data`, `cri.geo.district_master`). Total population 1,210,854,977,
  the published Census 2011 total for India.
- **Used for:** `population` and `urban_share` in `district_master.parquet` (contract C1); the
  population weights of the crosswalk (`cri.geo.crosswalk`); later, the Phase 1 D controls
  (agricultural worker share and the rest).
- **Known problems:**
  - Urban and rural are given for households, not persons, so `urban_share` is urban
    households over all households. It is close to the urban population share but not equal
    to it (urban households are a little smaller on average).
  - Names are spelt as in the Census tables (for example "North Twenty Four Parganas"); the
    district master keeps the boundary file's names, so A's tables do not change.
