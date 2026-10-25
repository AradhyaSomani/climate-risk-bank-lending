-- Warehouse schema (task list "Database Schema and API"), made idempotent with IF NOT EXISTS.
-- Parquet files in data/processed stay the source of truth; this database serves the API and
-- dashboard. Tables after "Person A hazard detail" are additions: they hold the per-event
-- hazard tables of contract C3 and the long-run baseline, which event_district summarises.

CREATE EXTENSION IF NOT EXISTS postgis;

-- Reference ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS district (
  district_id   INTEGER PRIMARY KEY,        -- Census 2011 district code
  name          TEXT NOT NULL,
  state         TEXT NOT NULL,
  state_code    SMALLINT,
  population    INTEGER,
  area_km2      REAL,
  urban_share   REAL,
  split_flag    BOOLEAN NOT NULL DEFAULT FALSE,
  geom          GEOMETRY(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS district_geom_idx ON district USING GIST (geom);

CREATE TABLE IF NOT EXISTS district_crosswalk (
  rbi_name      TEXT NOT NULL,
  rbi_state     TEXT NOT NULL,
  valid_from    DATE NOT NULL,
  valid_to      DATE,
  district_id   INTEGER NOT NULL REFERENCES district,
  weight        REAL NOT NULL CHECK (weight > 0 AND weight <= 1),
  match_type    TEXT,                       -- exact | normalized | fuzzy | manual | split
  PRIMARY KEY (rbi_name, rbi_state, valid_from, district_id)
);

CREATE TABLE IF NOT EXISTS district_edge (               -- adjacency for the graph model
  a INTEGER REFERENCES district,
  b INTEGER REFERENCES district,
  weight REAL NOT NULL DEFAULT 1,
  PRIMARY KEY (a, b)
);

-- Lending panel ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS credit_deposit (
  district_id   INTEGER NOT NULL REFERENCES district,
  quarter_end   DATE NOT NULL,
  bank_group    TEXT NOT NULL,
  measure       TEXT NOT NULL CHECK (measure IN ('credit','deposits')),
  sector        TEXT NOT NULL,
  amount_cr     DOUBLE PRECISION,           -- rupees crore, nominal
  n_offices     INTEGER,
  series_break  BOOLEAN NOT NULL DEFAULT FALSE,
  split_flag    BOOLEAN NOT NULL DEFAULT FALSE,
  imputed_share REAL CHECK (imputed_share BETWEEN 0 AND 1),
  data_version  TEXT NOT NULL,
  PRIMARY KEY (district_id, quarter_end, bank_group, measure, sector)
);

CREATE TABLE IF NOT EXISTS control_var (
  district_id INTEGER REFERENCES district,
  quarter_end DATE,
  nightlights DOUBLE PRECISION,
  rainfall_mm DOUBLE PRECISION,
  PRIMARY KEY (district_id, quarter_end)
);

-- Events and hazards -----------------------------------------------------
CREATE TABLE IF NOT EXISTS hazard_event (
  event_id      TEXT PRIMARY KEY,
  hazard_type   TEXT NOT NULL CHECK (hazard_type IN ('flood','cyclone')),
  name          TEXT,
  start_date    DATE NOT NULL,
  end_date      DATE,
  impact_quarter DATE NOT NULL,
  source        TEXT NOT NULL,
  emdat_id      TEXT
);

CREATE TABLE IF NOT EXISTS event_district (
  event_id      TEXT REFERENCES hazard_event,
  district_id   INTEGER REFERENCES district,
  flooded_share REAL,
  flooded_built_share REAL,
  track_dist_km REAL,
  max_wind_kt   REAL,
  treated       BOOLEAN NOT NULL,
  heavily_treated BOOLEAN NOT NULL DEFAULT FALSE,
  excluded      BOOLEAN NOT NULL DEFAULT FALSE,   -- exclusion zone
  PRIMARY KEY (event_id, district_id)
);

CREATE TABLE IF NOT EXISTS hazard_score (
  district_id   INTEGER REFERENCES district,
  score_version TEXT NOT NULL,                 -- rank_avg | weighted | pca | susceptibility
  hazard_type   TEXT NOT NULL,                 -- flood | cyclone | combined
  score         REAL NOT NULL,
  tier          SMALLINT NOT NULL CHECK (tier BETWEEN 1 AND 4),
  data_version  TEXT NOT NULL,
  PRIMARY KEY (district_id, score_version, hazard_type)
);

-- Results ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS exposure (
  quarter_end   DATE NOT NULL,
  bank_group    TEXT NOT NULL,
  sector        TEXT NOT NULL,
  tier          SMALLINT NOT NULL,
  share_credit  REAL NOT NULL,
  share_low     REAL,                           -- sensitivity range
  share_high    REAL,
  route         TEXT NOT NULL,                  -- group | annual_report | branch_alloc
  PRIMARY KEY (quarter_end, bank_group, sector, tier, route)
);

CREATE TABLE IF NOT EXISTS effect (
  event_id      TEXT NOT NULL,                  -- C4 event id, or 'pooled'
  estimator     TEXT NOT NULL,
  outcome       TEXT NOT NULL,
  bank_group    TEXT NOT NULL,
  sector        TEXT NOT NULL,
  window_start  SMALLINT NOT NULL,
  window_end    SMALLINT NOT NULL,
  estimate      DOUBLE PRECISION NOT NULL,
  ci_low        DOUBLE PRECISION NOT NULL,
  ci_high       DOUBLE PRECISION NOT NULL,
  ci_level      REAL,
  n_treated     INTEGER NOT NULL,
  n_control     INTEGER NOT NULL,
  pre_trend_p   REAL,
  is_primary    BOOLEAN NOT NULL DEFAULT FALSE,  -- C5 `primary` (a reserved word in SQL)
  code_version  TEXT NOT NULL,
  data_version  TEXT
);

CREATE TABLE IF NOT EXISTS scenario (
  scenario_id   TEXT PRIMARY KEY,
  scenario_type TEXT NOT NULL CHECK (scenario_type IN ('replay','shifted','scaled','compound','generated')),
  source_event  TEXT REFERENCES hazard_event,
  severity      REAL,
  hypothetical  BOOLEAN NOT NULL,
  description   TEXT
);

CREATE TABLE IF NOT EXISTS scenario_district (           -- footprint of each scenario
  scenario_id   TEXT REFERENCES scenario,
  district_id   INTEGER REFERENCES district,
  intensity     REAL NOT NULL,                  -- flooded share or wind kt
  heavily_treated BOOLEAN NOT NULL,
  beyond_observed BOOLEAN NOT NULL,
  PRIMARY KEY (scenario_id, district_id)
);

CREATE TABLE IF NOT EXISTS stress_result (
  scenario_id   TEXT REFERENCES scenario,
  hypothetical  BOOLEAN,
  bank_group    TEXT NOT NULL,
  metric        TEXT NOT NULL,                  -- d_credit | d_deposits | d_cd_ratio
  horizon       TEXT NOT NULL,                  -- q0_3 | q4_7 | q8_11
  unit          TEXT,                           -- pct | crore | pp
  median        DOUBLE PRECISION NOT NULL,
  lower         DOUBLE PRECISION NOT NULL,
  upper         DOUBLE PRECISION NOT NULL,
  interval_level REAL,
  var_share_effect REAL,
  var_share_hazard REAL,
  var_share_exposure REAL,
  var_share_generator REAL,
  code_version  TEXT NOT NULL,
  data_version  TEXT,
  PRIMARY KEY (scenario_id, bank_group, metric, horizon)
);

-- Model registry -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_run (
  run_id        TEXT PRIMARY KEY,               -- MLflow run id
  component     TEXT NOT NULL,                  -- flood_cnn | susceptibility | graph | statespace | causal_ml | extract
  baseline_name TEXT NOT NULL,
  baseline_score DOUBLE PRECISION,
  model_score   DOUBLE PRECISION,
  passed_gate   BOOLEAN NOT NULL,
  data_version  TEXT NOT NULL,
  code_version  TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Person A hazard detail ---------------------------------------------------
CREATE TABLE IF NOT EXISTS flood_extent (
  event_id            TEXT NOT NULL,          -- GFD-<dfo id> or the catalogue id
  district_id         INTEGER NOT NULL REFERENCES district,
  source              TEXT NOT NULL CHECK (source IN ('gfd','s1_unet','s1_otsu')),
  flooded_km2         REAL NOT NULL,
  flooded_share       REAL NOT NULL CHECK (flooded_share BETWEEN 0 AND 1),
  mapped_share        REAL NOT NULL CHECK (mapped_share BETWEEN 0 AND 1),
  flooded_built_share REAL,
  flooded_crop_share  REAL,
  duration_days       REAL,
  clear_view_share    REAL,
  data_version        TEXT NOT NULL,
  PRIMARY KEY (event_id, district_id, source)
);

CREATE TABLE IF NOT EXISTS cyclone_exposure (
  event_id        TEXT NOT NULL,              -- IMD-<storm id>
  district_id     INTEGER NOT NULL REFERENCES district,
  track_dist_km   REAL NOT NULL,
  closest_time    TIMESTAMPTZ NOT NULL,
  wind_kt_closest REAL NOT NULL,
  grade_closest   TEXT NOT NULL,
  landfall_time   TIMESTAMPTZ,
  within_radius   BOOLEAN NOT NULL,
  data_version    TEXT NOT NULL,
  PRIMARY KEY (event_id, district_id)
);

CREATE TABLE IF NOT EXISTS hazard_baseline (
  district_id                 INTEGER PRIMARY KEY REFERENCES district,
  gfd_events_hit              INTEGER,
  gfd_pixel_flood_count       REAL,
  gfd_max_flooded_share       REAL,
  gfd_events_mapped           INTEGER,
  gfd_events_hit_per_decade   REAL,
  gfd_record_years            REAL,
  landfall_count              INTEGER,
  landfall_count_strong       INTEGER,
  landfall_strong_per_decade  REAL,
  imd_record_years            REAL,
  perm_water_share            REAL,
  elev_mean_m                 REAL,
  slope_mean_deg              REAL,
  lowlying_share              REAL,
  rel_elev_median_m           REAL,   -- proxy for height above nearest drainage
  data_version                TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS flood_extent_district_idx ON flood_extent (district_id);
CREATE INDEX IF NOT EXISTS cyclone_exposure_district_idx ON cyclone_exposure (district_id);
CREATE INDEX IF NOT EXISTS credit_deposit_quarter_idx ON credit_deposit (quarter_end);

-- Upgrade a database built before B's C1, C2 and C5 columns were added (no-op on a new one)
ALTER TABLE district ADD COLUMN IF NOT EXISTS state_code SMALLINT;
ALTER TABLE district ADD COLUMN IF NOT EXISTS split_flag BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE district_crosswalk ADD COLUMN IF NOT EXISTS match_type TEXT;
ALTER TABLE credit_deposit ADD COLUMN IF NOT EXISTS n_offices INTEGER;
ALTER TABLE credit_deposit ADD COLUMN IF NOT EXISTS imputed_share REAL;
ALTER TABLE effect DROP CONSTRAINT IF EXISTS effect_event_id_fkey;
ALTER TABLE effect ADD COLUMN IF NOT EXISTS ci_level REAL;
ALTER TABLE effect ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE effect ADD COLUMN IF NOT EXISTS data_version TEXT;
ALTER TABLE stress_result ADD COLUMN IF NOT EXISTS hypothetical BOOLEAN;
ALTER TABLE stress_result ADD COLUMN IF NOT EXISTS unit TEXT;
ALTER TABLE stress_result ADD COLUMN IF NOT EXISTS interval_level REAL;
ALTER TABLE stress_result ADD COLUMN IF NOT EXISTS data_version TEXT;
