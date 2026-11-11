# Data card: RBI district deposits and credit (BSR)

Status: downloaded on 2026-10-25 (BSR-7 quarterly 2004 to 2022, the 2023 onwards statements, the annual volumes 2002 to 2026). Not available: September 2016 to March 2017, and the non-March quarters from 2023 (DBIE asks for a login and has no sign-up); both are excluded. Owner: Aradhya Somani (from 2026-10-25).

| Field | Value |
| --- | --- |
| Publisher | Reserve Bank of India, Database on Indian Economy (DBIE), https://data.rbi.org.in (the old address, dbie.rbi.org.in, is the one in releases up to 2021) |
| Returns behind it | BSR-7 (quarterly, until Dec 2022, all SCBs including RRBs and SFBs), then quarterly BSR-1 (credit) and BSR-2 (deposits), both excluding RRBs, and the annual BSR-1 (March, including RRBs, by place of utilisation) |
| Unit of observation | District × quarter (BSR-7 and Statement 4A), district × year (annual volumes) |
| Units | Change between years and tables: annual Table 2.4 in ₹ lakh to 2010, ₹ million 2011 to 2017, ₹ crore from 2018; Table 5.9/3.9 mostly ₹ thousand; Statement 4A in ₹ crore. Every file states its unit in a title row, and the reader converts each to ₹ crore |
| Quarter convention | Files report the last reporting Friday or the quarter's last day; we store the calendar quarter-end date (see `docs/contracts/README.md`) |
| License / terms | No open licence. The RBI site is "© Reserve Bank of India. All Rights Reserved." and its [terms of use](https://rbi.org.in/Commonman/English/Scripts/Disclaimer.aspx) grant no general reuse right; RBI publications state "Reproduction is permitted provided an acknowledgement of the source is made" ([example](https://rbi.org.in/scripts/bs_viewcontent.aspx?Id=2780)). No DBIE-specific terms found (checked 2026-10-25); look for a terms link in the DBIE footer when downloading and record it here. Project rule: raw files are never published (not in Git, not in a release; the DVC remote is private to the team). Derived district tables and figures may be published with the source line "Reserve Bank of India, DBIE, Basic Statistical Returns, accessed <date>". |
| Used in | Phase 0 A audit, Phase 1 C panel (contract C2), Phases 2 to 4 |

## How to download (record exactly what you did)

1. Open https://data.rbi.org.in in a normal browser. It can't be scripted from the project's cloud machine (the network blocks rbi.org.in hosts), and it may ask for a captcha.
2. On the home page, *Publications* lists the "Time-Series Publications" (seen on 2026-10-25). Take, in this order:
   - "Quarterly Spatial Distribution of Deposits and Credit": deposits, credit and number of offices by state and district each quarter (June 2026 was the latest release on 2026-10-25). It holds three entries, and the panel needs all three, district-wise tables only:
     - "Quarterly Statistics on Deposits and Credit of Scheduled Commercial Banks (from Quarter ended March 2004 to March 2017) - (Including Regional Rural Banks)";
     - the same from June 2017 to December 2022 (Including Regional Rural Banks);
     - "Spatial Distribution of Deposits and Credit - (Excluding Regional Rural Banks)", the series after BSR-7.
     The first two are BSR-7 with RRBs; the third leaves RRBs out, a coverage break at 2023 Q1.
   - "Annual Spatial Distribution of Deposits and Credit - (Including Regional Rural Banks)": the March figures with RRBs, to measure what leaving RRBs out of the quarterly series changes.
   - "Annual Basic Statistical Return (BSR)-1 on Credit by Scheduled Commercial Banks - (Including Regional Rural Banks)", district tables only: credit by occupation (sector) and by place of utilisation.
   - "Bank Branch Statistics", if it lists branches by bank and district (Phase 0 C).
   The quarterly BSR-1 and BSR-2 publications are not needed: their releases describe states and population groups only.
3. A statement gives several periods in one download, one block of columns per period (Statement 4A, March 2023 to March 2026, came as one file). The annual volumes come as one zip per year.
4. Save each file unchanged (never edit raw files) into one of three folders:
   - `data/raw/rbi/quarterly/`: district-wise statements only (Statement 4A and its BSR-7 equivalents). `rbi_first_look.py` and the panel reader read every file here, so nothing else goes in, and no two files may cover the same period. Name them `statement_4a_<first YYYY-MM>_to_<last YYYY-MM>.xlsx`.
   - `data/raw/rbi/annual_bsr/`: the annual volumes as `bsr_vol<NN>.zip`, and the loose tables of a release that has no zip in a folder named after its year (`2026_tables/`).
   - `data/raw/rbi/bsr7_2004_2016/`, `data/raw/rbi/bsr7_2017_2022/`, `data/raw/rbi/spatial_2023/`: the other statements of each quarterly entry (state tables, deposit types, size classes) and its notes.
5. Add one line per file to the download log below, and append the new files' checksums to `docs/raw_checksums.sha256` (run from the repo root: `shasum -a 256 data/raw/rbi/quarterly/statement_4a_*.xlsx >> docs/raw_checksums.sha256`, then sort the file; `python scripts/raw_checksums.py` would rewrite the whole file from what is on your disk).
6. Run `python scripts/rbi_first_look.py --out docs/00_rbi_first_look.md` and copy its numbers into `docs/00_rbi_audit.md`.

### Download log

| File name | Table | Periods | Downloaded on | By | Notes |
| --- | --- | --- | --- | --- | --- |
| `annual_bsr/bsr_vol31.zip` to `bsr_vol54.zip` (24 files) | "Basic Statistical Returns of Scheduled Commercial Banks in India", Vol 31 to 54: all tables of each year (`.xls` to 2015, `.xlsx` after; Vol 31 to 42 also have the whole volume as a PDF, Vol 50 its notes) | March 2002 to March 2025, one volume per year | 2026-10-25 | Aradhya Somani | District tables: 2.4 (deposits and credit by district and population group, to 2018), 2.14 (credit by district and population group, from 2019), 5.9 / 3.9 (credit by district and occupation) |
| `annual_bsr/2026_tables/` (44 tables and `Notes_on_Tables.pdf`) | "Outstanding Credit of Scheduled Commercial Banks in India", March 2026: Tables 1.1 to 1.14, 2.1 to 2.14, 3.1 to 3.9 | March 2026 | 2026-10-25 | Aradhya Somani | Table 1.14 (district credit to individuals by gender) is new in 2026 |
| `quarterly/statement_4a_2023-03_to_2026-03_march_only.xlsx` | "Spatial Distribution of Deposits and Credit (Excluding RRBs)", Statement 4A: offices, deposits and credit by district | March 2023, 2024, 2025, 2026 | 2026-10-25 | Aradhya Somani | March figures only; replace it if the period filter also offers the other quarters |
| `spatial_2023/` (8 statements and `BSR7_Notes_on_Tables.pdf`) | the same publication: Statements 1, 2, 3A, 3B, 4B, 5, 6A, 6B | March 2023 to March 2026 | 2026-10-25 | Aradhya Somani | 4B: deposits by type and district; 5: by centre (town) |
| `quarterly/statement_4a_2004-03_to_2016-06.xlsx` | "Quarterly Statistics on Deposits and Credit of SCBs (March 2004 to March 2017) - (Including RRBs)", Statement 4A | March 2004 to June 2016, 50 quarters | 2026-10-25 | Aradhya Somani | Stops at June 2016 although the entry's title says March 2017; credit is "Gross Bank Credit" |
| `quarterly/statement_4a_2017-06_to_2022-12.xlsx` | the same, June 2017 to December 2022 (Including RRBs), Statement 4A | June 2017 to December 2022, 23 quarters | 2026-10-25 | Aradhya Somani | |
| `bsr7_2004_2016/`, `bsr7_2017_2022/` (7 statements and `BSR7_Notes_on_Tables.pdf` each) | the same two entries: Statements 1, 2, 3A, 3B, 4B, 6A, 6B | as above | 2026-10-25 | Aradhya Somani | |
| `spatial_2023/Statement_No._1_..._quarterly_2023-03_to_2026-06.xlsx` | 2023 onwards entry, Statement 1 | March 2023 to June 2026, 14 quarters | 2026-10-25 | Aradhya Somani | Shows that the 2023 onwards entry has every quarter |
| not available | BSR-7 Statement 4A, September 2016 to March 2017 | 3 quarters | tried 2026-10-25 | Aradhya Somani | needs a DBIE login |
| not available | 2023 onwards Statement 4A, June, September and December quarters | 2023 to 2026 | tried 2026-10-25 | Aradhya Somani | needs a DBIE login |

`data/raw/` is in `.gitignore`. These files go to DVC once Phase 1 A sets it up, never into Git.

## Known problems

- Coverage changes between releases: BSR-7 (to December 2022) includes RRBs; from 2023 the March figures include them and the other quarters do not. See `docs/00_rbi_audit.md` sections 1 and 5.
- The source return changed after Dec 2022 (BSR-7 discontinued); since then the statements are built from BSR-1 and BSR-2. Statement 4A still has district credit after 2022 (checked for the March figures, 2023 to 2026).
- Merger of a non-bank with a bank on 1 July 2023 (HDFC with HDFC Bank): a level shift in private-bank credit and deposits from 2023 Q3. RBI adjusts its own growth figures for it.
- Location basis: the quarterly statements and annual Tables 2.4 / 2.14 give credit by place of sanction (the branch that books it); annual Tables 5.9 / 3.9 by place of utilisation. Accounts in the short BSR-1B return have no place of utilisation and are assumed to be used where sanctioned (Vol 39 notes). Both bases are in every annual volume, so Phase 0 B can compare them by district (`docs/00_location_basis.md`).
- Units change between years and tables (lakh, million, thousand, crore). Never assume one unit for a folder.
- Annual district deposits stop after March 2018 in the BSR-1 volumes (Table 2.14 is credit only). March 2019 to March 2022 needs the separate BSR-2 publication or the quarterly statements.
- District names follow RBI's district list, which takes up new districts late: Tamil Nadu's 2019 and 2020 districts first appear in March 2022. Spellings also change ("Cannur" in 2002, "Kannur" later; "Alapuzha").
- Districts and centres with fewer than three offices are not shown (blank).
- Reference date: until June 2016, June, September and December figures are for the last reporting Friday of the quarter and March for 31 March; since September 2016 every figure is for the last day of the quarter. The December to March change is two to three times larger before 2016 than after.
- The first BSR-7 entry's district statement ends in June 2016, not March 2017 as its title says; the three quarters in between need a DBIE login and are excluded.
- The quarterly statements label districts with today's state (Telangana from 2004) but keep each quarter's own district list.
- From September 2016 the quarterly survey reports bank credit without bills rediscounted with RBI and other institutions; until June 2016 it reported gross bank credit.
- RRBs were amalgamated from 43 to 28 banks in 2025-26. This changes the number of banks, not the district totals.
- District names follow the current district list of each release, not Census 2011. The Phase 1 B crosswalk maps them back.
- `-` or blank in the files means not reported. The reader stores it as missing, never as zero.

## How it is read

`src/cri/ingest/rbi_bsr.py` (`read_district_table`, `read_folder`) finds the header row, maps columns by keyword, reads the unit from the title rows, and converts to crore. It reads both a long file (one period, or a period column) and a wide statement with one block of columns per period (Statement 4A). It does not read the annual volumes yet; a reader for Tables 2.4 / 2.14 and 5.9 / 3.9, whose layout changes between 2002, 2005, 2011 and 2014, is still to come (the annual sector split and the place-of-utilisation basis). `scripts/rbi_first_look.py` prints the audit numbers and plots the test states.

## The quarterly panel (Phase 1 B and C, November 2026)

`make data` runs four steps (`src/cri/pipeline.py`):

1. `cri.ingest.rbi_bsr:build` reads the three Statement 4A files in `data/raw/rbi/quarterly/`
   into `data/interim/rbi_district_quarterly.parquet`: 77 quarters (March 2004 to June 2016,
   June 2017 to December 2022, March 2023 to March 2026), 821 state and district labels,
   all in ₹ crore.
2. `cri.geo.district_master:build` writes `district_master.parquet` (contract C1).
3. `cri.geo.crosswalk:build` maps every label to Census 2011 districts
   (`crosswalk_rbi_to_c2011.parquet`, contract C1). Every decision that is not an exact name
   match is in `configs/crosswalk.yaml` (or Person A's `configs/district_aliases.yaml`), with
   its reason, and listed in `data/interim/crosswalk_review.csv` for checking by hand.
4. `cri.exposure.panel:build` writes `panel_credit_deposit.parquet` (contract C2) and the
   coverage report `docs/eval_reports/panel_balance.md`.

How labels become Census 2011 districts:

- **Same district, other name** (about 570 exact, 67 close spellings confirmed by hand, about
  40 renames such as Gurugram, Prayagraj, Kalaburagi): weight 1.
- **Districts created after 2011** (about 140 labels, among them the 2016 Telangana and 2022
  Andhra Pradesh reorganisations): weight 1 to the Census 2011 district they were mostly
  carved from. Where another 2011 district also gave territory, both are flagged
  `split_flag`. Each parent was checked against the drop in RBI's office counts in the
  quarter the new label first appears.
- **Census 2011 districts created between 2004 and 2011** (39 districts, for example Tapi,
  Palwal, the eight Jammu and Kashmir districts of 2007, Mumbai Suburban): until a child
  first appears in RBI's tables, its figures are inside its parent's label, so that label is
  shared between parent and children by Census 2011 population (match_type `split`). Those
  rows carry `imputed_share` > 0 in the panel.
- **Delhi** is one RBI label ("NEW DELHI") for nine Census 2011 districts; it is shared by
  population and all nine are flagged.
- Labels that change in the middle of the 2017 file (Sikkim's four districts were renamed in
  2017 and the old names kept a few offices until March 2018) are summed; office counts show
  no double counting.

Checks: every RBI figure falls in exactly one crosswalk interval (`check_labels_used`); each
label's weights sum to 1 in every interval; all 640 districts are in the panel for every
quarter; Kerala, Odisha and Tamil Nadu are complete; and office counts, which are not an
outcome, are checked for jumps. The 14 jumps left (`docs/eval_reports/panel_balance.md`) are
either the population-share approximation in the first quarter a pre-2011 child is reported
(offices follow branches, not people: Mumbai, Mewat, Tarn Taran, Bandipore, Ganderbal, Imphal
East, Tapi, Nalbari, North and Middle Andaman) or single-quarter blips in RBI's own counts
(Gondiya in December 2008, Champhai in March 2019, Senapati in March 2019).

Not reported (null amount, never zero): Kurung Kumey, Dibang Valley and Anjaw (Arunachal
Pradesh) in every quarter, and a few small districts in some quarters, because RBI does not
print districts with fewer than three offices. 98.8% of district-quarter-measure rows have a
figure.

Not done yet: real (deflated) series, the credit-deposit ratio and growth rates (they need a
documented price index), the outlier review against the source (it means looking at
district series around events, so it waits for the signed pre-registration), and the
annual sector split.
