# Read-only API (Phase 5A)

`src/cri/api/`: a FastAPI service over the project's tables. It never writes.

```bash
make api-sample                                   # contract samples, no data needed
make api                                          # data/processed (the source of truth)
CRI_API_SOURCE=postgres DATABASE_URL=... make api # the warehouse (docs/warehouse.md)
CRI_API_FALLBACK=1 make api                       # data/processed, samples where a file is missing
```

Open http://127.0.0.1:8000/docs for the generated reference.

| Endpoint | Table (contract) | Filters |
|---|---|---|
| `/health` | row count of every table, `null` when not built | |
| `/districts` | district master (C1); `geometry=true` adds simplified GeoJSON | `state`, `simplify_deg` |
| `/hazard-scores` | `hazard_scores` (C3) | `hazard_type`, `score_version`, `district_id` (repeatable), `tier` |
| `/hazard-indicators` | `hazard_indicators` (C3) | `district_id` |
| `/events`, `/events/{id}/districts` | `events`, `event_district` (C4) | `hazard_type`; `treated` |
| `/scenarios`, `/scenarios/{id}/districts` | `scenarios`, `scenario_district` (C4) | `scenario_type` |
| `/exposure` | B's `exposure` table | `bank_group`, `sector`, `route`, `quarter_end` |
| `/effects` | `effects` (C5) | `event_id`, `estimator`, `outcome`, `bank_group` |
| `/stress-results` | `stress_results` (C5) | `scenario_id`, `bank_group`, `metric`, `horizon` |
| `/model-runs` | `model_runs.parquet` (Phase 2B gates) | `component` |

Every response is an envelope: `resource`, `data_version` (from the rows, else
`configs/project.yaml`), `source` (parquet, sample or postgres), `n`, `rows`, and where it
applies `estimators`, `routes` and `interval` (which columns hold the bounds). A footprint
response also says whether the scenario is `hypothetical`.

Rule from the task list: no stress number without its interval. `/stress-results` withholds
any row whose `median`, `lower` or `upper` is missing and reports how many in
`withheld_without_interval`. `tests/api/` checks this and checks every endpoint's rows
against its contract.
