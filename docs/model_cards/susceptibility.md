# Flood susceptibility (Phase 2B-C)

## Purpose
Say where floods are likely from terrain and land cover alone, so that districts with a
short or empty flood record are not scored as safe just because the satellite record missed
them. Output: `data/processed/susceptibility_district.parquet` and, because the gate passed,
an extra flood score version `susceptibility` in `hazard_scores.parquet` (contract C3). It
does not enter the combined score or the three main versions.

## Data
- Run: `python -m cri.hazard.flood_grid` (event grids), `python -m cri.ml.susceptibility.features`,
  `python -m cri.ml.susceptibility.train`, then `python -m cri.hazard.score` to add the version.
- Grid: 0.02 degrees (about 2 km), 1,575 x 1,500 cells over India; about 790,000 cells inside
  a district and observed by at least one Global Flood Database event.
- Features (`cri.ml.susceptibility.features`, cached in
  `data/interim/susceptibility_features_0.02.npz`): elevation, slope, share below the
  low-lying threshold and height above the lowest cell within about 10 km (Copernicus DEM),
  permanent-water share (JRC), distance to coast and to the nearest Natural Earth river,
  built-up and cropland share (ESA WorldCover 2021). No flood history in the main model.
- Labels: the 147 GFD India events on the same grid (`cri.hazard.flood_grid`), permanent
  water removed; a cell counts as flooded in an event above 5% flooded share.
- Split: spatial blocks of 2 x 2 degrees as groups in 5-fold group CV; every score is on
  cells of blocks the model never saw. 200,000 cells are drawn at random for each test
  (`cv.max_cells`) to keep a run under two minutes on a laptop; blocks stay whole as groups.
- Label problems: MODIS misses short, cloudy and urban floods, and the record is
  2000-2018 only. "Not flooded" therefore often means "not seen".

## Baseline and gate
Fixed in `configs/ml/susceptibility.yaml` before the run.

- Gate test: target = cell flooded in any event from 2012 on (the cut-off in
  `configs/hazard.yaml`), among cells those events observed. Baseline = the cell's flood count
  before 2012, which needs no training. Metric: AUC on held-out blocks.

| Model (later floods, held-out blocks) | AUC, seed 42 | Seeds 1, 2 |
| --- | --- | --- |
| Flood count before 2012 (baseline) | 0.880 | 0.879, 0.880 |
| LightGBM, terrain and land cover only | **0.905** | 0.904, 0.900 |
| Logistic regression, same features | 0.850 | 0.849, 0.823 |
| LightGBM, features plus earlier count | 0.949 | 0.950, 0.947 |
| LightGBM on shuffled labels (leak check) | 0.504 | 0.501, 0.501 |

**Gate: passed** (0.905 against 0.880; margin 0). The shuffled-label run sits at 0.50, so
the block split does not leak.

- District level (mean over a district's sampled cells, 604 districts with later events):
  Spearman with the later flooded share is 0.73 for terrain only, 0.78 for the earlier
  count and 0.83 for both. So at district level the model is **not** better than the record
  where a record exists; its value is where the record is thin, and combined with the record.
- Static test (any GFD flood, 2000-2018, held-out blocks): LightGBM 0.891, logistic 0.842.
- Independent check, Kerala 2018 (not in GFD, so never a label): within Kerala, AUC for the
  seven worst-hit districts of the PDNA is 0.90 with the susceptibility version against 0.57
  for the rank_avg flood score. Only 14 districts, so read it as a sign, not a measurement.
  Pathanamthitta, one of the worst hit, is still near the bottom (0.06).

## Model
LightGBM classifier: 400 trees, learning rate 0.05, 31 leaves, at least 50 cells per leaf,
row and column subsampling 0.8. The district score is the mean predicted probability over
all of a district's cells from a model fitted on every observed cell (static target).
Gain importance: height above local minimum 0.39, elevation 0.18, distance to coast 0.12,
distance to river 0.12, slope 0.09, permanent water 0.06, cropland 0.03, built-up and
low-lying share under 0.01. Ablations run: logistic regression; adding the earlier count.

## Compute
Cloud container CPU (4 cores shared with the U-Net run), about 80 seconds per run with
200,000 cells per test; the full 790,000 cells did not finish in 30 minutes there. MLflow
experiment `susceptibility` in `mlruns/`, runs 952d8b1773a34bc8a749e2d8b669a6f8 and
4935b8a6eb424aa1a816bd9eb8c5b092 (final, with the shuffled-label check). Gate rows in
`data/processed/model_runs.parquet`.

## Intended use and limits
- Use: a second flood view next to the record-based score, and a flag for districts the
  record may miss. Shown as its own version, never mixed into tiers silently.
- Labels are GFD floods, so the model learns what MODIS sees: large riverine floods on the
  Gangetic and Brahmaputra plains. Flash floods in hills, urban flooding and coastal surge are
  under-learned, and the score is low for them.
- One land-cover year (2021) for all events.

## Failure cases
- Tiny or island districts: Lakshadweep comes out in the top tier (all coast and low
  elevation, a few cells only); Mahe is near the bottom. Treat both as not scored.
- Delhi (East and Central) and Jehanabad, Araria and Uttar Dinajpur are two tiers higher than
  on the record: low, flat and near rivers, but floods there were short or embanked.
- Hill districts hit by landslides and flash floods score low in Kerala (Idukki 0.16,
  Wayanad 0.14 on the percentile scale, tier 1). Uttarakhand districts sit in the middle
  (0.31 to 0.62, tiers 1 and 2), which says little about flash-flood risk there.
