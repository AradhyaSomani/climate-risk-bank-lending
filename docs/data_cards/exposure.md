# Lending exposure tables (Phase 2 D)

Built by `python -m cri.exposure.district_exposure` from the C2 panel and the C3 hazard
scores; settings in `configs/exposure.yaml`. Run it only after the pre-registration is signed
(`prereg-v1`): the tables are levels of credit and deposits, not event outcomes, but they
include post-event quarters.

| File | One row per | Columns |
| --- | --- | --- |
| `exposure_by_tier.parquet` | quarter, bank group, measure, sector, score version, hazard type, tier | `amount_cr`, `share` of the all-India total over districts with a figure, `districts`, `coverage` (share of the 640 districts with a figure), `series_break` |
| `exposure_concentration.parquet` | quarter, bank group, measure, sector, score version, hazard type | `top10_share`, `top50_share` (the N most hazardous districts with a figure), `hhi` (Herfindahl index of the amount across districts) |
| `exposure_by_state.parquet` | the same, by Census 2011 state | `amount_cr`, `high_share` (tiers 3 and 4) |
| `exposure_trend.parquet` | bank group, measure, sector, score version, hazard type, regime or break | `pp`: the high-tier share's slope in percentage points a year inside each reporting regime, or its jump across a series break |

Tiers are those of `hazard_scores.parquet`: 1 low (below the 50th percentile), 2 medium,
3 high (75th to 90th), 4 very high. Every score version is kept; `report_version`
(`weighted`) is the one shown in the report, and the others feed the sensitivity range
(Phase 2 F).

## Known gaps

- Bank groups and sectors: the quarterly panel holds all banks and all sectors only. The
  sector split (agriculture, industry, services, personal) needs the annual BSR district
  tables, which are on the Mac (`data/raw/rbi/annual_bsr`) but have no reader yet. Bank-group
  exposure needs the routes in Phase 2 E.
- Quarters RBI did not publish (September 2016 to March 2017, and the non-March quarters from
  June 2023) have no rows.
- Shares are over the districts with a figure that quarter; `coverage` says how many.
