# Data contracts

A contract fixes the columns, types, units and keys of a table that one person produces and the other reads. Both of us build against the contract, not against each other's code, so either side can work on a stub before the real data exists.

| Contract | File | Producer | Consumer | Tables |
| --- | --- | --- | --- | --- |
| C1 districts | `C1_districts.yaml` | B | A | `district_master`, `crosswalk_rbi_to_c2011` |
| C2 panel | `C2_panel.yaml` | B | A | `panel_credit_deposit` |
| C3 hazard | to be written by A | A | B | flood and cyclone footprints, hazard scores |
| C4 events | to be written by A | A | B | `events`, `event_district` |
| C5 results | `C5_results.yaml` | B | A | `effects`, `stress_results` |

## Rules

- A contract changes only through a pull request that the other person approves. Bump `version` in the YAML on every change: patch for a clarification, minor for an added column, major for a renamed or removed column or a changed unit.
- Every table has a toy sample in `samples/`. The numbers in the samples are made up and must never be used in an analysis.
- Units and conventions shared by all contracts:
  - Money is in **rupees crore**, nominal, unless the column name says otherwise.
  - Quarters are identified by their **last calendar day** (`2018-09-30`), never by a label like `2018Q3` or by the first day.
  - Districts are **Census 2011** codes (`district_id`, integer). Later districts are mapped back to 2011 through the C1 crosswalk.
  - Dates are ISO `YYYY-MM-DD`.

## Checking a file

```bash
python scripts/validate_contracts.py                       # all toy samples
python scripts/validate_contracts.py C2 panel_credit_deposit data/processed/panel_credit_deposit.parquet
```

The validator reads CSV or Parquet. It exits with code 1 and lists every problem if a file breaks its contract, so CI can run it on every pull request.

## What the YAML can say

Per column: `dtype` (`int`, `float`, `str`, `bool`, `date`, `geometry`), `nullable`, `min`, `max`, `allowed` (list of values), `pattern` (regex), `quarter_end: true` (date must be the last day of a calendar quarter). Per table: `primary_key` (must be unique, no nulls) and `checks`, which name table-level rules implemented in `src/cri/contracts/validate.py`.
