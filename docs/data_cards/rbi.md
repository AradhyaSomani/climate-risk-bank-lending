# Data card: RBI district deposits and credit (BSR)

Status: draft, written before the first full download (owner: Aradhya Somani from 2026-10-25). Update every section once the files are in `data/raw/rbi/`.

| Field | Value |
| --- | --- |
| Publisher | Reserve Bank of India, Database on Indian Economy (DBIE), https://data.rbi.org.in (the old address, dbie.rbi.org.in, is the one in releases up to 2021) |
| Returns behind it | BSR-7 (quarterly, until Dec 2022, all SCBs including RRBs and SFBs), then quarterly BSR-1 (credit) and BSR-2 (deposits), both excluding RRBs, and the annual BSR-1 (March, including RRBs, by place of utilisation) |
| Unit of observation | District × quarter (× bank group where published) |
| Units | TODO from the file header (lakh or crore); the pipeline converts everything to rupees crore |
| Quarter convention | Files report the last reporting Friday or the quarter's last day; we store the calendar quarter-end date (see `docs/contracts/README.md`) |
| License / terms | No open licence. The RBI site is "© Reserve Bank of India. All Rights Reserved." and its [terms of use](https://rbi.org.in/Commonman/English/Scripts/Disclaimer.aspx) grant no general reuse right; RBI publications state "Reproduction is permitted provided an acknowledgement of the source is made" ([example](https://rbi.org.in/scripts/bs_viewcontent.aspx?Id=2780)). No DBIE-specific terms found (checked 2026-10-25); look for a terms link in the DBIE footer when downloading and record it here. Project rule: raw files are never published (not in Git, not in a release; the DVC remote is private to the team). Derived district tables and figures may be published with the source line "Reserve Bank of India, DBIE, Basic Statistical Returns, accessed <date>". |
| Used in | Phase 0 A audit, Phase 1 C panel (contract C2), Phases 2 to 4 |

## How to download (record exactly what you did)

1. Open https://data.rbi.org.in in a normal browser. It can't be scripted from the project's cloud machine (the network blocks rbi.org.in hosts), and it may ask for a captcha.
2. On the home page, *Publications* lists the "Time-Series Publications" (seen on 2026-10-25). Take, in this order:
   - "Quarterly Spatial Distribution of Deposits and Credit": deposits, credit and number of offices by state and district each quarter, the continuation of the BSR-7 tables (June 2026 was the latest release on 2026-10-25). Every quarter it offers, back to the earliest (the Kosi 2008 window needs 2006 Q3 onward; the gate needs at least 10 years).
   - "Annual Spatial Distribution of Deposits and Credit - (Including Regional Rural Banks)": the March figures with RRBs, to measure what leaving RRBs out of the quarterly series changes.
   - "Annual Basic Statistical Return (BSR)-1 on Credit by Scheduled Commercial Banks - (Including Regional Rural Banks)", district tables only: credit by occupation (sector) and by place of utilisation.
   - "Bank Branch Statistics", if it lists branches by bank and district (Phase 0 C).
   The quarterly BSR-1 and BSR-2 publications are not needed: their releases describe states and population groups only.
3. Note here whether a table gives many quarters in one download or one file per quarter: TODO.
4. Save each file unchanged into `data/raw/rbi/` (never edit raw files). Name them `rbi_district_<table>_<YYYY-MM>.xlsx` if DBIE gives them generic names, for example `rbi_district_bsr7_2018-09.xlsx`.
5. Add one line per file to the download log below, and append the files' checksums to `docs/raw_checksums.sha256` with `shasum -a 256 data/raw/rbi/* >> docs/raw_checksums.sha256` (run from the repo root; `python scripts/raw_checksums.py` would rewrite the whole file from what is on your disk).
6. Run `python scripts/rbi_first_look.py --out docs/00_rbi_first_look.md` and copy its numbers into `docs/00_rbi_audit.md`.

### Download log

| File name | Table | Quarters | Downloaded on | By | Notes |
| --- | --- | --- | --- | --- | --- |
| TODO | | | | | |

`data/raw/` is in `.gitignore`. These files go to DVC once Phase 1 A sets it up, never into Git.

## Known problems

- Coverage changes between releases (with or without regional rural banks): BSR-7 includes RRBs, the quarterly BSR-1 and BSR-2 releases from 2023 do not. See `docs/00_rbi_audit.md` sections 1 and 5.
- The source return changed after Dec 2022 (BSR-7 discontinued). The quarterly BSR-1 releases since then describe credit by state, not district; check that the Quarterly Spatial Distribution tables still have district credit after December 2022.
- Merger of a non-bank with a bank on 1 July 2023 (HDFC with HDFC Bank): a level shift in private-bank credit and deposits from 2023 Q3. RBI adjusts its own growth figures for it.
- Location basis: credit is attributed to the branch that books it, not where it is used. See `docs/00_location_basis.md` (Phase 0 B).
- District names follow the current district list of each release, not Census 2011. The Phase 1 B crosswalk maps them back.
- `-` or blank in the files means not reported. The reader stores it as missing, never as zero.

## How it is read

`src/cri/ingest/rbi_bsr.py` (`read_district_table`, `read_folder`) finds the header row, maps columns by keyword, reads the unit from the title rows, and converts to crore. `scripts/rbi_first_look.py` prints the audit numbers and plots the test states.
