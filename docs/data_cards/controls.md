# Controls: rainfall, night lights, Census 2011, loan waivers, elections and state shocks (Phase 1 D)

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
| `waiver_commercial`, `waiver_coop_only`, `quarters_since_waiver` | `loan_waivers` in `configs/controls.yaml` | State-level, copied to every district of the state (or of a `region`, below) |
| `election_state`, `election_general` | `state_elections`, `general_elections` in `configs/controls.yaml` | Assembly or Lok Sabha results declared in the quarter |
| `quarters_to_state_election` | `state_elections` | Quarters until the next assembly results (0 in the results quarter). Null after a state's last listed election and in union territories without an assembly |
| `state_shock`, `state_shock_name` | `state_shocks` in `configs/controls.yaml` | A large state policy shock began in the quarter, and its name |

## How the Earth Engine tables are made

`python -m cri.ingest.ee_controls` (needs the `gee` extra and an Earth Engine project, as
for Sentinel-1) builds one image per product with a band per month (rainfall, VIIRS) or
year (harmonised series), averages each band over every district, and exports CSV tables to
the Google Drive folder `cri-controls`, 160 districts per task. Boundaries are simplified by
0.005 degrees (about 500 m) before upload to keep requests small; at the 5.5 km CHIRPS grid
that makes no difference, and for night lights it moves only pixels on the boundary. Copy the
CSVs to `data/raw/controls/` (DVC tracks them with the rest of `data/raw`).

## Exports so far

First full export on 13 November 2026 (project `cri-earth-engine`, Drive folder
`cri-controls`, 4 batches of 160 districts per product), after `--check` showed:

| Product | Collection | Images in window | First | Last |
| --- | --- | --- | --- | --- |
| `rain` | `UCSB-CHG/CHIRPS/DAILY` | 12,965 days | 1991-01-01 | 2026-06-30 |
| `ntl_viirs` | `NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG` | 150 months | 2014-01-01 | 2026-06-01 |
| `ntl_harmonized` | `.../Harmonized_NTL/dmsp` (to 2013) | 14 years | 2000 | 2013 |
| `ntl_harmonized` | `.../Harmonized_NTL/viirs` (from 2014) | 8 years | 2014 | 2021 |

- Task ids: rain `H3E6SBNEGJDRBPX6KGKEXFDI`, `AVS5B4ETT6LHQXC7L7EUWBYA`,
  `MAPM375CDQI2JV5RILLQI4PI`, `HO4TLCNLCTPRB6EHX46BELMI`; VIIRS `W5MQFU5AWJZTK75IZABDS7ZS`,
  `FNX725OY7MJESK73OUF5A4KK`, `AKRTKRH2YI7DWPA4JYG4EN5M`, `HEP4PEMGHA6Y7WB2K4E4SUCY`;
  harmonised `5LLJU675RJQJZDTXRMDLWTJI`, `LIOT7UWGMVMYFSLVPQBRE66P`,
  `B3BAI3DJTZDVK4HVNIMCPGPJ`, `GPT5SN6L2MEXBJFWK7QSX25M`.
- The harmonised series was exported twice. The first run (before the fix that takes 2013
  from DMSP only) averaged the DMSP and VIIRS values for 2013; its files were replaced and
  differ from the kept ones in 2013 only. The VIIRS monthly export ran with the old April
  2012 start; Earth Engine holds nothing before 2014, so its files are the same as they would
  be now.
- Checks on the CSVs: all 640 districts in each product, no district in two batches. Rainfall
  has every month from January 1991 to June 2026 with no gaps; the all-India district mean is
  about 1,300 mm a year, highest in July (313 mm) and lowest in December (13 mm). 201 of the
  72,000 VIIRS district-months are slightly negative (none below -0.05) and are set to 0.
- `make data` afterwards: 57,600 rows; filled rain 100%, VIIRS 56% (2014 Q1 to 2026 Q2, 50 of
  90 quarters), harmonised 80% (2004 to 2021, 72 of 90 quarters).

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

## Elections

137 assembly results from 2004 to May 2026 for the 30 Census 2011 states and union
territories with an assembly, and the five Lok Sabha results (2004, 2009, 2014, 2019, 2024).
The date is the counting day, when the Election Commission declared the results; the
quarter of the poll itself is the same or the one before. Credit to farmers from
public-sector banks rises in the year before a state election (Cole 2009, *American
Economic Journal: Applied Economics* 1(1)), which is why the distance to the next election
is kept as well as the results quarter. Bihar voted twice in 2005 (a hung assembly in
February, then November). Every date is marked `checked: false` until checked against the
ECI statistical report for that election.

## Regions: Telangana and the rest of Andhra Pradesh

Census 2011 has one Andhra Pradesh. After the split on 2 June 2014, Telangana (Census 2011
districts 532-541, Adilabad to Khammam) and the rest of the state (542-554) have their own
elections and their own 2014 loan waivers. `regions` in `configs/controls.yaml` lists the
districts of each, and an entry with `region:` covers those districts only. Until 2014 both
use the state entries.

## State policy shocks

Five shocks that hit one state and can move district credit on their own: the Andhra Pradesh
microfinance ordinance (October 2010), which stopped most microfinance repayments in the
state; the state's bifurcation (June 2014); the Kashmir unrest and curfews (July 2016);
the revocation of Article 370 with months of communications shutdown (August 2019); and the
ethnic violence in Manipur (May 2023). Nationwide shocks (demonetisation, GST, the COVID-19
lockdown and the 2020 loan moratorium) hit every district in the same quarter, so the
quarter fixed effects absorb them; they are not columns. Dates are marked `checked: false`.

## Known problems

- The harmonised series stops in 2021 and VIIRS monthly starts in 2014, so no night-light
  series covers every quarter: use the harmonised series for 2004-2021 and VIIRS for later
  quarters, or the two with an overlap check in 2014-2021.
- When an export is run again, Google Drive keeps both files (the new one as
  `<name> (1).csv`); `make data` stops and names the files until only one copy is left.
- VIIRS monthly radiance is noisy in the monsoon (cloud) months and has gaps over the
  northern hills in summer; the quarterly mean uses whichever months have data.
- `quarters_to_state_election` is null at the end of the window for states whose next
  election (2027 or 2028) is not listed yet: 11 to 19% of their quarters. Add the dates
  when the Election Commission announces them.
- The shock list is a judgement of which state events were large enough; it is short on
  purpose and is not exhaustive.
