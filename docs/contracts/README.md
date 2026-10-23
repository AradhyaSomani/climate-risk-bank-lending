# Contracts between the two sides

Each contract is a YAML schema for the tables one side produces and the other consumes. A toy
sample for every table lives in `tests/fixtures/contracts/`, so both people can build against a
stub before the real data exists.

| Contract | Producer | Consumer | Tables |
| --- | --- | --- | --- |
| [C1](C1_district_master.yaml) | B | A | `district_master`, `crosswalk_rbi_to_c2011` |
| [C2](C2_panel_credit_deposit.yaml) | B | A | `panel_credit_deposit` |
| [C3](C3_hazard_tables.yaml) | A | B | `flood_extent_district_event`, `cyclone_exposure_district_event`, `hazard_scores` |
| [C4](C4_events.yaml) | A | B | `events`, `event_district` |
| [C5](C5_results.yaml) | B | A | `effects`, `stress_results` |

## Rules

- A contract changes only through a pull request that the other person approves.
- C1, C2 and C5 were stubbed by A so the validator could be written; B owns them and should
  correct names, bank groups and sectors once the RBI tables are opened.
- CI validates every sample on every pull request; once processed files exist, run
  `python -m cri.contracts --processed` before handing a table over.

## What a column spec can say

`dtype` (int, float, str, bool, date, datetime, geometry), `nullable`, `min` / `max`
(`exclusive_min`), `allowed`, `quarter_end`. Table checks: `sum_to_one` (grouped),
`sum_to_one_row`, `ordered`, `implies`, `not_both`.

```bash
python -m cri.contracts --samples
python -m cri.contracts C3 hazard_scores data/processed/hazard_scores.parquet
```
