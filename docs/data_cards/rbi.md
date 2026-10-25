# Data card: RBI district deposits and credit (BSR)

Status: draft, written before the first full download. Update every section once the files are in `data/raw/rbi/`.

| Field | Value |
| --- | --- |
| Publisher | Reserve Bank of India, Database on Indian Economy (DBIE), https://dbie.rbi.org.in |
| Returns behind it | BSR-7 (quarterly, until Dec 2022), then BSR-1 (credit) and BSR-2 (deposits) |
| Unit of observation | District × quarter (× bank group where published) |
| Units | TODO from the file header (lakh or crore); the pipeline converts everything to rupees crore |
| Quarter convention | Files report the last reporting Friday or the quarter's last day; we store the calendar quarter-end date (see `docs/contracts/README.md`) |
| License / terms | TODO: copy the DBIE terms of use. Until confirmed, treat raw files as not redistributable and share only the download steps |
| Used in | Phase 0 A audit, Phase 1 C panel (contract C2), Phases 2 to 4 |

## How to download (record exactly what you did)

1. Open https://dbie.rbi.org.in in a normal browser (it may need a captcha, so it can't be scripted).
2. Find the district-wise deposits and credit table. TODO: write the menu path here.
3. Choose all states and the widest range of quarters it allows; download as Excel.
4. Save each file unchanged into `data/raw/rbi/` (never edit raw files). Name them `rbi_district_<table>_<YYYY-MM>.xlsx` if DBIE gives them generic names.
5. Add one line per file to the download log below.

### Download log

| File name | Table | Quarters | Downloaded on | By | Notes |
| --- | --- | --- | --- | --- | --- |
| TODO | | | | | |

`data/raw/` is in `.gitignore`. These files go to DVC once Phase 1 A sets it up, never into Git.

## Known problems

- Coverage changes between releases (with or without regional rural banks). See `docs/00_rbi_audit.md` section 5.
- The source return changed after Dec 2022 (BSR-7 discontinued).
- Location basis: credit is attributed to the branch that books it, not where it is used. See `docs/00_location_basis.md` (Phase 0 B).
- District names follow the current district list of each release, not Census 2011. The Phase 1 B crosswalk maps them back.
- `-` or blank in the files means not reported. The reader stores it as missing, never as zero.

## How it is read

`src/cri/ingest/rbi_bsr.py` (`read_district_table`, `read_folder`) finds the header row, maps columns by keyword, reads the unit from the title rows, and converts to crore. `scripts/rbi_first_look.py` prints the audit numbers and plots the test states.
