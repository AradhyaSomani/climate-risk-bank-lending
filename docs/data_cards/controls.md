# Controls: rainfall, night lights, Census 2011 and state loan waivers (Phase 1 D)

Built by `cri.exposure.controls` into `data/processed/controls_district_quarter.parquet`:
one row per Census 2011 district and calendar quarter, March 2004 to the end of the study
period. Settings are in `configs/controls.yaml`.

| Column | Source | Notes |
| --- | --- | --- |
| `population_2011`, `urban_share_2011` | Census 2011 (`district_master.parquet`) | Urban share is of households (`census2011.md`) |
| `ag_worker_share_2011` | Census 2011 | (cultivators + agricultural labourers) / all workers |
| `literacy_2011` | Census 2011 | literates / total population (the Census rate uses ages 7+, so this is lower) |
| `rain_mm`, `rain_anom` | CHIRPS v2.0 daily (Earth Engine `UCSB-CHG/CHIRPS/DAILY`) | Monthly totals averaged over the district, summed to quarters (all three months needed). Anomaly = quarter / mean of the same calendar quarter 1991-2020 - 1 |
| `ntl_viirs` | VIIRS DNB monthly, stray-light corrected (`NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG`) | District mean of `avg_rad` (nW/cm²/sr), averaged over the quarter's months with data, small negative monthly means (background noise on dark land) set to 0; from January 2014, the first month Earth Engine holds |
| `ntl_harmonized` | Harmonised DMSP and VIIRS annual night lights (Li, Zhou, Zhao and Zhao 2020, *Scientific Data* 7:168), Earth Engine community catalogue `projects/sat-io/open-datasets/Harmonized_NTL/{dmsp,viirs}` | DMSP scale (0-63), annual, same value for the four quarters of a year. The bridge across the 2013-14 change of satellite: the authors' harmonisation, not ours. Both parts hold 2013; 2013 is taken from the DMSP part |
| `waiver_commercial`, `waiver_coop_only`, `quarters_since_waiver` | `loan_waivers` in `configs/controls.yaml` | State-level, copied to every district of the state |

## How the Earth Engine tables are made

`python -m cri.ingest.ee_controls` (needs the `gee` extra and an Earth Engine project, as
for Sentinel-1) builds one image per product with a band per month (rainfall, VIIRS) or
year (harmonised series), averages each band over every district, and exports CSV tables to
the Google Drive folder `cri-controls`, 160 districts per task. Boundaries are simplified by
0.005 degrees (about 500 m) before upload to keep requests small; at the 5.5 km CHIRPS grid
that makes no difference, and for night lights it moves only pixels on the boundary. Copy the
CSVs to `data/raw/controls/` (DVC tracks them with the rest of `data/raw`).

`--check` lists, per product, how many source images fall in the window and the first and
last date, so the configured end dates can be moved as the sources update.

## Licences (to confirm before release)

- CHIRPS: Climate Hazards Center, UC Santa Barbara; released into the public domain (CC0)
  as stated on the CHC data page. Cite Funk et al. (2015), *Scientific Data* 2:150066.
- VIIRS monthly composites: Earth Observation Group, Payne Institute, Colorado School of
  Mines; CC BY 4.0. Cite Elvidge et al. (2017).
- Harmonised night lights: figshare dataset of Li et al. (2020), CC BY 4.0.
- Census 2011: see `census2011.md`.

These terms are recorded from the publishers' stated licences; the pages could not be opened
from our cloud environment, so check each before publishing derived tables.

## Loan waivers

Each entry has the state, announcement date, scheme, which lenders it covered and the amount
announced. A waiver limited to cooperative banks barely touches scheduled commercial banks,
which is what the RBI panel measures, so it gets its own flag. The list follows RBI's Report
of the Internal Working Group to Review Agricultural Credit (September 2019) and SBI
Research's Special Report on Agriculture (18 July 2022); exact dates are from press reports
of the state orders and are marked `checked: false` until each is checked against the order.
Telangana's 2014 waiver is under Andhra Pradesh, its Census 2011 state.

## Known problems

- Rainfall and night lights are empty until the Earth Engine CSVs are in
  `data/raw/controls/`.
- VIIRS monthly radiance is noisy in the monsoon (cloud) months and has gaps over the
  northern hills in summer; the quarterly mean uses whichever months have data.
- State elections and other state policy shocks (task list Phase 1 D, fourth item) are not
  in yet.
