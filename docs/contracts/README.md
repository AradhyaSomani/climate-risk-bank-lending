# Data contracts

A contract fixes the columns, types, units and keys of a table that one person produces and the
other reads. Both of us build against the contract, not against each other's code, so either
side can work on a stub before the real data exists.

| Contract | File | Producer | Consumer | Tables |
| --- | --- | --- | --- | --- |
| C1 districts | [`C1_districts.yaml`](C1_districts.yaml) | B | A | `district_master`, `crosswalk_rbi_to_c2011` |
| C2 panel | [`C2_panel.yaml`](C2_panel.yaml) | B | A | `panel_credit_deposit` |
| C3 hazard | [`C3_hazard_tables.yaml`](C3_hazard_tables.yaml) | A | B | `flood_extent_district_event`, `cyclone_exposure_district_event`, `hazard_indicators`, `hazard_scores` |
| C4 events | [`C4_events.yaml`](C4_events.yaml) | A | B | `events`, `event_district`, `scenarios`, `scenario_district` |
| C5 results | [`C5_results.yaml`](C5_results.yaml) | B | A | `effects`, `stress_results` |

## Rules

- A contract changes only through a pull request that the other person approves. Bump `version`
  in the YAML on every change: patch for a clarification, minor for an added column, major for
  a renamed or removed column or a changed unit.
- Every table has a toy sample in `tests/fixtures/contracts/`. The numbers in the samples are
  made up and must never be used in an analysis. Samples are validated with `full=False`, which
  skips checks that only make sense on the complete table (the 640-district row count).
- Units and conventions shared by all contracts:
  - Money is in **rupees crore**, nominal, unless the column name says otherwise.
  - Quarters are identified by their **last calendar day** (`2018-09-30`), never by a label
    like `2018Q3` or by the first day.
  - Districts are **Census 2011** codes (`district_id`, integer). Later districts are mapped
    back to 2011 through the C1 crosswalk.
  - Dates are ISO `YYYY-MM-DD`.
- CI validates every sample on every pull request; once processed files exist, run
  `python -m cri.contracts --processed` before handing a table over.

## Checking a file

```bash
python -m cri.contracts --samples                          # all toy samples
python -m cri.contracts C2 panel_credit_deposit data/processed/panel_credit_deposit.parquet
python -m cri.contracts --processed                        # every processed file that exists
python scripts/validate_contracts.py                       # same, without installing the package
```

The validator (`src/cri/contracts.py`) reads CSV or Parquet. It exits with code 1 and lists
every problem if a file breaks its contract.

## What the YAML can say

Per column: `dtype` (`int`, `float`, `str`, `bool`, `date`, `datetime`, `geometry`),
`nullable` (default false), `min`, `max` (`exclusive_min`), `allowed` (list of values),
`pattern` (regex), `quarter_end: true` (date must be the last day of a calendar quarter).

Per table: `primary_key` (must be unique) and `checks`. A check is either the name of a rule in
`TABLE_CHECKS` (`row_count_640_if_full`, `weights_sum_to_one`, `valid_to_after_valid_from`,
`deposits_sector_all`, `interval_contains_estimate`, `interval_contains_median`,
`window_ordered`, `var_shares_sum_to_one`) or a dict with a `kind`: `sum_to_one` (grouped),
`sum_to_one_row`, `ordered`, `implies`, `not_both`.

## In the warehouse

`src/cri/db/schema.sql` stores every C1, C2 and C5 column. C5 `primary` is a reserved word in
SQL, so it is stored as `is_primary` and renamed back when the API reads from PostgreSQL.
Pooled effects have `event_id = 'pooled'`, so `effect.event_id` has no foreign key to the
event table.
