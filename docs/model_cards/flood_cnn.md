# U-Net flood mapper on Sentinel-1 (Phase 2B-B)

## Purpose
Map flood water from Sentinel-1 radar where the Global Flood Database has nothing, Kerala
2018 first (docs/decision_log.md). The output is a `flooded` raster that
`cri.hazard.zonal_stats` turns into district flooded shares with source `s1_unet` (contract
C3), next to the Otsu map from `cri.ingest.sentinel1`.

## Data
- Sen1Floods11 v1.1 hand-labelled chips (`docs/data_cards/sen1floods11.md`), 446 chips of
  512 x 512 at 10 m from 11 events, cut into 256 x 256 patches; patches with more than half
  the label missing are dropped. Inputs: VV and VH in dB, clipped and scaled to 0-1.
- Split by event, never by patch. Test: India (68 chips) and Bolivia (15 chips). Validation:
  Sri Lanka (42 chips), used only to pick the epoch. Training: the other 8 events (321 chips,
  1,157 patches; 160 validation and 294 test patches). India is held out entirely so that the
  Kerala run has no Indian training data at all.
- Label problems: one Indian event only (2016-08-12); labels mix permanent and flood water;
  hand labels follow the analyst's reading of Sentinel-2 as well as radar.

## Baseline and gate
Fixed in `configs/ml/flood_cnn.yaml`: water IoU per held-out event, pooled over the event's
valid pixels, then averaged over events. The model has to beat the best baseline.

| Method (test events) | India | Bolivia | Mean IoU | Mean F1 |
| --- | --- | --- | --- | --- |
| **U-Net, VV + VH, base 16** | **0.553** | **0.702** | **0.628** | **0.769** |
| Fixed VH threshold (fitted on training events, -24 dB) | 0.432 | 0.500 | 0.466 | 0.635 |
| Fixed VV threshold (fitted on training events) | 0.462 | 0.394 | 0.428 | 0.598 |
| Otsu on VH, per chip | 0.243 | 0.404 | 0.324 | 0.483 |
| Otsu on VV, per chip | 0.220 | 0.350 | 0.285 | 0.440 |

**Gate: passed** (0.628 against 0.466 for the best baseline, and better on both events).
Change detection, the third baseline, needs a pre-event scene, which Sen1Floods11 does not
ship; it is run on Earth Engine exports only.

Per-chip Otsu does badly because many chips have little water, so the histogram has no
second mode; a single threshold fitted on training events is the fairer baseline.

## Model
U-Net, depth 4, 16 channels in the first block (`base_channels`), 2 input channels, 2
classes. Loss: 0.5 Dice + 0.5 cross-entropy with inverse-frequency class weights, ignoring
missing labels. Adam, learning rate 0.001, weight decay 0.0001, batch 16, flips and 90-degree
rotations as augmentation, seed 42. 15 epochs (the config's 40 was cut to fit CPU time); the
epoch with the best validation IoU is kept (epoch 9, validation IoU 0.669). Validation IoU
moves a lot between epochs (0.47 to 0.67), so the epoch choice matters and a second seed
would show how much.

Ablations (same split, settings and seed; `--channels vv vh dem slope` adds the Copernicus
90 m DEM and its slope resampled onto each chip):

| Run | India | Bolivia | Mean IoU | Best epoch | MLflow run |
| --- | --- | --- | --- | --- | --- |
| SAR only, VV + VH (kept) | 0.553 | 0.702 | 0.628 | 9 | 039b6085... |
| SAR plus terrain | 0.564 | 0.666 | 0.615 | 8 | 644987bf... |

Terrain helps a little on India (+0.011) and hurts on Bolivia (-0.037); with one seed and
validation IoU moving by 0.1 between epochs, neither difference is above noise. The SAR-only
model stays the main one: it needs no DEM at prediction time. Both pass the gate. Not run
yet: base 32 and no augmentation.

## Compute
Cloud container CPU: 84 minutes for 15 epochs on 3 shared threads (SAR only), 45 minutes on
4 threads (SAR plus terrain). MLflow
experiment `flood_cnn`, run 039b60853c0746e8b04591e1a4e330cf. Weights:
`data/interim/flood_cnn/sar_base16.pt` (and `data/models/flood_cnn/` since it passed).
Scores per event: `data/interim/flood_cnn/results.csv`.

## Intended use and limits
- Use: the flood map for events GFD missed (Kerala 2018), through
  `python -m cri.ml.flood_cnn.predict <weights> <scene.tif> <out.tif>` on a backscatter export
  (`python -m cri.ingest.sentinel1 --kind backscatter ...`, needs Earth Engine).
- Tested on two events only. An IoU of 0.55 on India means about half the water pixels
  are matched. District flooded shares from it need the same checks as the Otsu map.
- Radar cannot see water under dense canopy or in built-up areas (double bounce), so urban
  and forest flooding are missed by every method here.

## Failure cases
- Not inspected chip by chip yet. Expected from the method: steep terrain (radar shadow
  looks like water), wet soil and smooth surfaces (airports, sand) as false water, and
  flooded vegetation as false dry.
- The Kerala 2018 run has not been done: it waits for the Earth Engine export
  (user to-do).
