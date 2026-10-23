# Warehouse (PostgreSQL + PostGIS)

Parquet files in `data/processed/` are the source of truth. The database serves the API and
the dashboard.

```bash
createdb cri && psql -d cri -c "CREATE EXTENSION postgis"
make db DATABASE_URL=postgresql://<user>@localhost:5432/cri
```

- Schema: `src/cri/db/schema.sql`, the task list's schema made idempotent, plus three
  tables for A's hazard detail: `flood_extent`, `cyclone_exposure`, `hazard_baseline`.
- Loader: `src/cri/db/load.py` (`scripts/load_db.py`). Each table is copied into a temporary
  table and upserted on its primary key; rows no longer in the file are deleted (except
  `district`, which other tables reference). Tables without a file yet are skipped, so the
  load can run at any point in the project.
- `district` comes from B's `district_master.parquet` when it exists, otherwise from the
  provisional DataMeet geometry.
- Spatial index: `district_geom_idx` (GIST). Extra B-tree indexes on `district_id` for the
  hazard tables and on `quarter_end` for the panel.

Tested on PostgreSQL 16 with PostGIS 3.4 (`tests/db/`, run with `CRI_TEST_DATABASE_URL`
pointing at a scratch database): loading twice gives identical counts, removed rows leave
the table, the polygon query uses the GIST index, and the district-event-score join works.
A full load of the current hazard tables (640 districts, 53,520 cyclone rows) takes about
two seconds.
