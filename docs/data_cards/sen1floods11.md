# Sen1Floods11 v1.1

- **Source:** Bonafilia et al. (2020), *Sen1Floods11: a georeferenced dataset to train and test deep learning flood algorithms for Sentinel-1*, CVPR Workshops. Public bucket `gs://sen1floods11/v1.1/`; code at github.com/cloudtostreet/Sen1Floods11.
- **Licence:** not stated. The STAC collection says `"license": "proprietary"` and the repository has no licence file. Use for research with citation; do not redistribute the chips. Ask Cloud to Street if anything beyond that is needed.
- **Coverage:** 11 flood events, 2016-08-12 to 2019-09-17 (Bolivia, Ghana, India, Cambodia/Mekong, Nigeria, Pakistan, Paraguay, Somalia, Spain, Sri Lanka, USA); 446 hand-labelled chips, 68 of them India (one event, 2016-08-12, descending orbit 77), plus about 4,385 weakly labelled chips.
- **Content:** 512x512 chips at 10 m, EPSG:4326. `S1Hand` (VV, VH in dB), `S2Hand`, `LabelHand` (-1 no data, 0 dry, 1 water), `S1OtsuLabelHand`, `JRCWaterHand`.
- **Known problems:** official splits are random within events (only Bolivia held out), so they overstate generalisation; one India event only; labels mix permanent and flood water.
- **Used for:** training and testing the U-Net and the Otsu baseline (Phase 2B-B) with leave-one-event-out splits.
