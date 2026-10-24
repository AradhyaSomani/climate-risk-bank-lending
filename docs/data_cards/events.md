# Event catalogue and treatment flags (Phase 3A, contract C4)

Built by `python -m cri.events.catalogue` (or `make events`) into `data/processed/events.parquet`
and `event_district.parquet`. Rules are in `configs/events.yaml`; they are placeholders
until the pre-registration fixes them.

## Sources
- Event list, dates and the matching GFD and IMD ids: `data/events/events_candidates.csv`
  (Phase 0 audit).
- Flood footprints: `flood_extent_district_event` (GFD now; Sentinel-1 is preferred once it
  exists). Cyclone footprints: `cyclone_exposure_district_event` (IMD best track).
- Neighbours for the exclusion zone: `district_edges.parquet` (Phase 2B-D).
- Other things that happened in the same windows: `data/events/confounders.csv`, each with a
  source URL and a `verified` flag.

## Rules (current placeholders)
- Flood: treated above 5% of district area flooded, heavily treated above 15%, only inside the
  event's states (GFD records often span a whole monsoon spell; the Kosi 2008 record also
  floods Assam and Uttar Pradesh).
- Cyclone: treated within 100 km of the track at SCS or stronger, heavily treated within
  50 km at VSCS or stronger.
- Exclusion zone: partly affected districts (flooded above 1%, or within 200 km at CS) and
  every district sharing a border with a treated one.
- Impact quarter: the quarter of landfall for cyclones, of the start date for floods.

## Current catalogue (data version dev)

| event_id | hazard_type | impact_quarter | treated | heavy | excluded |
| --- | --- | --- | --- | --- | --- |
| FL-2008-KOSI | flood | 2008-09-30 | 18 | 14 | 85 |
| FL-2013-UKD | flood | 2013-06-30 | 0 | 0 | 0 |
| CY-2013-PHAILIN | cyclone | 2013-12-31 | 16 | 10 | 23 |
| CY-2014-HUDHUD | cyclone | 2014-12-31 | 4 | 2 | 13 |
| FL-2015-CHENNAI | flood | 2015-12-31 | 3 | 0 | 14 |
| CY-2016-VARDAH | cyclone | 2016-12-31 | 4 | 0 | 7 |
| FL-2018-KERALA | flood | 2018-09-30 | 0 | 0 | 0 |
| CY-2018-GAJA | cyclone | 2018-12-31 | 9 | 3 | 14 |
| CY-2019-FANI | cyclone | 2019-06-30 | 22 | 12 | 30 |
| CY-2020-AMPHAN | cyclone | 2020-06-30 | 12 | 6 | 24 |
| CY-2020-NIVAR | cyclone | 2020-12-31 | 7 | 0 | 16 |
| CY-2021-TAUKTAE | cyclone | 2021-06-30 | 6 | 3 | 31 |
| CY-2021-YAAS | cyclone | 2021-06-30 | 8 | 3 | 17 |
| CY-2023-BIPARJOY | cyclone | 2023-06-30 | 2 | 0 | 7 |
| CY-2023-MICHAUNG | cyclone | 2023-12-31 | 7 | 0 | 11 |

## Known problems
- Kerala 2018 and Uttarakhand 2013 have no footprint yet (not in GFD); they are listed with
  no district rows until the Sentinel-1 maps exist.
- Chennai 2015 has only 3 treated districts because GFD barely sees urban flooding (Chennai
  district 0.2% flooded); the Sentinel-1 footprint should replace it.
- Amphan, Tauktae and Yaas fall in COVID-19 quarters (see the confounders list).
