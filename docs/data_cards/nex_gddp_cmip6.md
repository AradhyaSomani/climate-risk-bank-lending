# NEX-GDDP-CMIP6 (NASA Earth Exchange Global Daily Downscaled Projections)

Status: terms recorded on 2026-10-25 for the Phase 0 G licence check. Not used yet; it is
needed only for the optional climate-projection extension (Phase 4E).

- **Source:** NASA Earth Exchange, Thrasher et al. (2022), documentation at
  https://doi.org/10.7917/OFSG3345. NetCDF in the public bucket `s3://nex-gddp-cmip6`
  (us-west-2, [AWS Open Data registry](https://registry.opendata.aws/nex-gddp-cmip6)), a
  cloud-optimised GeoTIFF copy in `s3://nex-gddp-cmip6-cog`, and the Earth Engine collection
  [`NASA/GDDP-CMIP6`](https://developers.google.com/earth-engine/datasets/catalog/NASA_GDDP-CMIP6).
- **Licence:** CC0 1.0 for every output. Some models were first released under CC BY-SA 4.0,
  following their CMIP6 inputs, but since September 2022 NASA makes all NEX-GDDP-CMIP6 outputs
  available under a blanket CC0 licence. Earth Engine images may still carry a `license`
  property inherited from the CMIP6 metadata; the catalogue says the blanket CC0 licence
  supersedes it. No attribution is required, but cite Thrasher et al. (2022) and the bias
  correction paper, Thrasher et al. (2012), HESS 16, 3309-3314.
- **Coverage:** daily, 0.25 degree (about 25 km), 1950-2014 historical runs and 2015-2100
  for SSP2-4.5 and SSP5-8.5 in the Earth Engine copy (check the bucket for other scenarios
  before use). 34 models in the Earth Engine copy. Variables include `pr`
  (precipitation, kg m-2 s-1), `tas`, `tasmin`, `tasmax`, `hurs`, `huss`, `rlds`, `rsds`
  and `sfcWind`; some models lack some variables (`hurs` is missing for BCC-CSM2-MR, NESM3
  and part of KIOST-ESM).
- **What may be published:** anything derived from it (CC0), including district rainfall
  statistics per scenario.
- **Known problems:** statistical downscaling with bias correction to observations; it does
  not add physical detail at 25 km, so district-scale extremes inherit the parent model's
  biases. Rainfall projections link only indirectly to flood footprints, which is why Phase
  4E keeps projections separate from the main stress test. No future updates are planned.
- **Used for:** nothing yet. If Phase 4E goes ahead: daily rainfall per district for a few
  models and two scenarios, to scale the frequency of the generated flood events.
