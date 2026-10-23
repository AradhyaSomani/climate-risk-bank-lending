# Cyclone footprint check: computed landfall versus IMD reports

`cri.hazard.cyclone_footprint` finds landfall as the first interpolated track point (30-minute
step) that falls on mainland India after a point at sea. Checked against published crossing
times on 2026-10-23 (data version `dev`, IMD workbook 1982-2026 via the imdtrack mirror).

| Storm | Computed landfall (UTC) | Computed district | Reported crossing | Source | Agrees |
| --- | --- | --- | --- | --- | --- |
| Fani 2019 | 2019-05-03 04:00 | Puri (387) | close to Puri, 02:30-04:30 UTC 3 May | [IMD RSMC report](https://rsmcnewdelhi.imd.gov.in/uploads/archive/60/60_a53fa0_fani.pdf) | Yes |
| Amphan 2020 | 2020-05-20 10:30 | South 24 Parganas (343) | between Digha and Hatiya near the Sundarbans, 15:30-17:30 IST (10:00-12:00 UTC) 20 May | [IMD press release 21 May 2020](https://mausam.imd.gov.in/backend/assets/press_release_pdf/PRESS_RELEASE_dated_21st_May_2020.pdf) | Yes |
| Hudhud 2014 | 2014-10-12 07:00 | Visakhapatnam (544) | Visakhapatnam coast around noon IST (06:30 UTC) 12 Oct | [The News Minute](https://www.thenewsminute.com/article/hudhud-makes-landfall-andhra-noon-be-very-severe-six-hours-16169) | Yes (within 30-60 min) |
| Phailin 2013 | 2013-10-12 17:00 | Ganjam (388) | near Gopalpur (Ganjam), late evening IST 12 Oct | not re-checked against a document | District yes; time not verified |
| Vardah 2016 | 2016-12-12 09:00 | Chennai (603) | near Chennai, afternoon IST 12 Dec | not re-checked against a document | District yes; time not verified |

Island territories (Andaman and Nicobar, Lakshadweep) are excluded from the landfall test;
without that rule Hudhud's and Phailin's "landfall" was their passage over the Andamans.

Maps for a visual check: `docs/figures/cyclone_fani_2019.png`, `cyclone_amphan_2020.png`,
`cyclone_hudhud_2014.png` (districts within 100 km at cyclonic-storm strength or stronger are
outlined in red).

Whole record: 422 storms with at least two fixes, 211 with a mainland landfall, 890
district-storm pairs within the placeholder radius rule (100 km, grade CS or stronger) across
99 storms.
