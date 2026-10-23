# JRC Global Surface Water v1.4

- **Source:** Pekel et al. (2016), Nature 540, 418-422. Tiles in the public bucket `gs://global-surface-water/downloads2021/` (also Earth Engine `JRC/GSW1_4/GlobalSurfaceWater`).
- **Licence:** produced under the Copernicus Programme, free of charge without restriction of use; cite the paper.
- **Coverage:** 1984-2021, 30 m, 10x10 degree tiles (for example `occurrence_70E_10Nv1_4_2021.tif`).
- **Used for:** permanent water share per district (Phase 1H) and masking permanent water out of flood extents.
- **Processing (`cri.hazard.baseline`):** read at full 30 m resolution in row chunks; the share of pixels with occurrence >= 90% is computed in each 0.005-degree cell (20 x 20 JRC pixels) and then area-weighted to districts as `perm_water_share`. Averaging occurrence before thresholding was rejected because it erases narrow rivers.
