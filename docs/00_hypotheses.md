# Phase 0 F: Pre-registration of the event study

Drafted by Aradhya Somani on 2026-10-25; open items settled on 2026-11-14 after the Phase 0 E
power check · Signed by Aradhya Somani, who now does both the data and the econometrics ·
Status: **final draft, binding once signed in section 9**

Written before any post-event credit or deposit figure has been computed. The RBI audit
(`docs/00_rbi_audit.md`) looks only at coverage, units and all-India totals, and the
location-basis test (`docs/00_location_basis.md`) only at March 2007, before every main event. The signatory confirms at sign-off not having looked at any either. The hazard
side (footprints, treatment flags) is built, so the treated district counts below are known;
they come from hazard data only.

Once section 9 is signed, this file is committed as it stands and tagged `prereg-v1`;
the commit date is its timestamp. After that it changes only through `docs/decision_log.md`,
with the date, the reason and whether outcomes had been seen. Anything not fixed here is
exploratory and is labelled so wherever it is reported. The items that were open in the
draft are settled below; each was decided without any post-event outcome (the power check,
`docs/eval_reports/power_check.md`, uses only pseudo impact dates before each event).

## 1. Question

Research question 2: what happened to district credit and deposits after the large Indian
floods and cyclones, compared with similar districts that were not hit? Every test is
two-sided: credit may fall (losses, lower demand) or rise (reconstruction lending, relief
schemes, restructuring), and deposits may rise (relief and insurance inflows) or fall
(households drawing down savings).

## 2. Data

- Outcomes: the C2 panel (`panel_credit_deposit.parquet`): quarterly credit and deposits in
  rupees crore per Census 2011 district, after the C1 crosswalk. Built from RBI's Basic
  Statistical Returns as audited in `docs/00_rbi_audit.md`.
- Treatment: the C4 event catalogue (`events.parquet`, `event_district.parquet`), from the
  rules in `configs/events.yaml` as they stand on the signing date.
- Quarters flagged `series_break` (the first quarter of a new RBI reporting regime: June
  2017 and March 2023) are kept as data. A robustness run drops event windows that cross a
  break. (The draft made them missing; that removed every Fani district, whose quarter −8 is
  June 2017. Decision log, 2026-11-11 and 2026-11-14.)
- Quarters RBI published for no district (September 2016 to March 2017; the non-March
  quarters from June 2023) are missing for everyone and are never filled.

## 3. Confirmatory outcomes and estimator

**Primary outcomes (co-primary):** log credit and log deposits, all banks and all sectors
(`bank_group = all`, `sector = all`).

**Primary summary:** the average effect over event quarters 0 to 3 (the impact quarter and
the three after it).

**Primary tests:** four, one per outcome and hazard type: credit after floods, credit after
cyclones, deposits after floods, deposits after cyclones. Holm's correction at a family-wise
level of 5 percent is applied across these four. Nothing else is a confirmatory test.

**Primary estimator:** event-by-event difference-in-differences with matched controls,
pooled by stacking (one stack per event, with its own treated and control districts):

y(i,e,t) = a(i,e) + l(t,e) + sum over k of b(k) · 1[t − t0(e) = k] · D(i,e) + u(i,e,t)

for district i, event e and quarter t; t0(e) is the event's impact quarter, D(i,e) = 1 for
its treated districts, k runs from −8 to +12 with k = −1 left out, a are district-by-event
and l quarter-by-event fixed effects. The primary summary is the mean of b(0) to b(3). One
stacked regression per hazard type. The estimator is first written by hand in
`events/did.py` for one event and checked against an established package (Phase 3B).

**Inference:** standard errors clustered by district. Because there are few treated
clusters, the p-value for each of the four primary tests is the larger of two:

1. Randomization inference: treatment reassigned at random among the event's eligible
   districts of the same states, 999 draws (the pooled statistic recomputed for each draw).
2. A placebo-date test: the same pooled estimate computed with each event's impact quarter
   moved to every earlier quarter whose window (−8 to +3) ends before the real impact
   quarter, with no district contributing quarters within 12 quarters after any catalogue
   event that treated or excluded it; 999 pooled draws, one random placebo date per event.
   The p-value is the share of placebo estimates at least as large in absolute value as the
   real one.

The second test was added after the power check showed that the first alone rejects the real
Odisha cyclone districts in 21% to 57% of placebo windows where the true effect is zero:
coastal districts move apart from the rest of their states even without a cyclone. Taking the
larger p-value keeps the size at or below 5% if either test is valid. A wild cluster
bootstrap and state-clustered errors are reported next to them.

**Secondary (reported, not tested as findings):** the same summary for quarters 4 to 7 and 8
to 11; the credit-to-deposit ratio; the full event-time path b(k).

## 4. Treatment, controls and timing

Copied from `configs/events.yaml` (2026-10-25); the file is the source if they ever differ.

| Rule | Floods | Cyclones |
| --- | --- | --- |
| Treated | more than 5% of district area flooded, inside the event's states | track within 100 km at severe cyclonic storm (SCS) strength or more |
| Heavily treated (dose-response only) | more than 15% flooded | within 50 km at very severe (VSCS) or more |
| Exclusion zone (not a control) | flooded above 1%, or flooded outside the event's states | within 200 km at cyclonic storm (CS) strength or more |
| Also excluded from controls | districts sharing a border with a treated district | same |

- **Impact quarter (event time 0):** the calendar quarter of the start date for floods and of
  landfall for cyclones. RBI's quarter-end figures are dated to the calendar quarter end.
- **Window:** 8 quarters before to 12 after. A district enters an event's stack only if it
  has the outcome for every quarter from −8 to +3 that RBI published for any district;
  later quarters may be missing. A quarter RBI published for nobody is skipped: it drops out
  of the pre-period means and, if it falls in quarters 0 to 3, out of the primary summary for
  that event (Chennai's summary is then the mean of quarters 0 to 2, Kerala's pre-period has
  five quarters). As drafted, the rule would have removed Chennai and Kerala entirely.
- **Controls:** districts that are neither treated nor in the exclusion zone of that event,
  and not treated by any other main event within the window. For each treated district, the
  five nearest controls (with replacement) by Mahalanobis distance on: mean log level and
  mean growth of the outcome over quarters −8 to −1, log population, urban share and
  agricultural share, plus the mean harmonised night lights (`ntl_harmonized`, Phase 1D) over
  the calendar years of quarters −8 to −1. Balance is
  reported before and after matching. A same-state version (controls only from the event's
  states) is the first robustness check.
- **Main events:** the seven in `configs/events.yaml` `main_events`: Bihar Kosi floods 2008,
  Phailin 2013, Hudhud 2014, Chennai floods 2015, Kerala floods 2018, Fani 2019, Amphan 2020.
  Treated districts from the current hazard tables: Kosi 18, Phailin 16, Hudhud 4, Chennai 3,
  Kerala 3, Fani 22, Amphan 12.
- **Kerala:** the footprint is the Sentinel-1 change-detection (Otsu) map with the windows in
  `configs/hazard.yaml` (`sentinel1`; `docs/decision_log.md`, 2026-10-28 and 2026-11-14),
  built and frozen before any Kerala outcome was looked at. It treats Alappuzha, Kottayam
  and Thrissur; the other four of the seven districts the Kerala PDNA (2018, p. 13) names as
  worst hit fall in the exclusion zone. Robustness: the seven PDNA districts as the treated
  set, with the same controls.
- **Chennai:** kept in the pooled flood estimate under the window rule above (the draft's
  open choice between dropping Chennai and shortening every window to +2 is settled this
  way, which keeps quarter +3 for the other six events).
- **Event exclusion rules:** an event is dropped from the pooled primary estimate (and still
  reported on its own) if it has fewer than 3 treated districts or fewer than 10 eligible
  controls with complete data over quarters −8 to +3. The other eight catalogue events
  (Vardah, Gaja, Nivar, Tauktae, Yaas, Biparjoy, Michaung, Uttarakhand) are robustness only.
- **Metro and headquarters districts:** the rule comes from the location-basis test (Phase 0 B,
  `docs/00_location_basis.md`, section B3). Every district stays in the main specification.
  The six largest credit centres and the districts whose credit by sanction and by
  utilisation differ by more than a factor of 1.25 (both fixed from March 2007) are flagged,
  and each group is dropped in a robustness check. Dropping them outright would remove
  Chennai from its own event.

## 5. Expected direction and size

These are priors to compare the results with, not claims to confirm. Sizes are for the
quarters 0 to 3 average unless stated, as percentage changes relative to matched controls.

| Outcome | Floods | Cyclones | Reasoning |
| --- | --- | --- | --- |
| Credit | near zero, between −3% and +3%; falling to between −2% and −5% by quarters 4 to 11 | the same pattern, with the later fall larger where farm and fishing assets were destroyed | Outstanding credit moves slowly: loans are restructured or put under moratorium, not written off, in the first year, and relief lending adds to the stock. Beyer, Narayanan and Thakur (2022) find credit rising in Kerala in the quarter after the 2018 floods, mainly housing. Das, Majilla and Saurav (2022), with RBI branch data for 2000 to 2012, find loans outstanding about 5% lower over two years (agriculture about 7%), back by year four. |
| Deposits | positive, between 0% and +5% | positive, between 0% and +5% | Relief payments, insurance claims and transfers are paid into bank accounts, and spending falls (ATM withdrawals and household spending fell in Kerala). The Caribbean evidence (Brei, Mohan and Strobl 2019) points the other way, so a fall is possible. |
| Credit-to-deposit ratio | a small fall, up to 3 percentage points | the same | Follows from deposits rising faster than credit in the short run. |

Effects of this size are close to what a district panel can detect at all. The Phase 0 E
power check (`docs/eval_reports/power_check.md`) puts the pooled minimum detectable effect
at 5.4% for credit after floods, 5.8% for credit after cyclones, 5.1% for deposits after
floods and 7.7% for deposits after cyclones (the largest of three ways of measuring it). A 5%
effect is at the edge of what the design can see, and an effect of 2 to 3% will most likely
read as "no detectable change". The write-up says so whatever the estimates are.

## 6. Decision rules

- **Power and the Phase 0 gate:** the plausible effect size is 5% (the two-year fall in Das et
  al.). An event passes the power check if its own minimum detectable effect for the quarters
  0 to 3 average on log credit, at 80% power and a 5% two-sided test, is 10% or less, taking
  the largest of the three MDEs in the power check (same-state randomization, randomization
  among all districts, and the real set's placebo-date error). The gate needs at least 4
  passing events. Result (2026-11-14): Kosi, Phailin, Fani and Amphan pass (MDEs 6.7%, 8.9%,
  8.2% and 8.1%); Hudhud, Chennai and Kerala, with 3 or 4 treated districts each, do not
  (12.2%, 13.0% and 12.7%) and stay in the pooled estimate, which is what the four primary
  tests use. The gate is met, with no margin. Had it failed, the event study would have
  switched to Fallback 2 (continuous flood intensity on all districts).
- **Pre-trends:** if the joint test of b(−8) to b(−2) rejects at 5% for an event, that event is
  reported but left out of the pooled primary estimate, and the parallel-trends sensitivity
  (how large a trend violation would erase the result) is shown for it.
- **Placebos:** fake impact dates 4 and 8 quarters before the real one, and untreated
  districts treated as if hit. If placebo estimates are as large as the real one, the result
  is reported as not distinguishable from noise.
- **Leave-one-event-out:** the pooled estimate is recomputed without each event in turn. If
  dropping one event changes the sign or the significance of a primary result, the write-up
  says the result rests on that event.
- **Usefulness for the stress test (Phase 3 gate):** if the 95% interval of a pooled primary
  summary is wider than 10 percentage points (−5% to +5%, say), the Phase 4 stress test uses
  scenario ranges instead of that point effect, and says so on its first page.
- **Series breaks:** if the RBI audit finds a break at the end of 2022 (BSR-7 discontinued),
  windows stop at 2022 Q4. This shortens only Amphan's window (to quarter +10).
- **Simulation check:** before any real estimate is read, each estimator must recover a
  planted −5% effect in the real panel with roughly nominal interval coverage (Phase 3B). An
  estimator that fails is not used for the confirmatory tests.

## 7. Exploratory, labelled as such

Splits by bank group, credit sector, urban versus rural, hazard tier and earlier flood
experience; the heavily treated dose-response; staggered DiD (Callaway and Sant'Anna) and
synthetic DiD as robustness of the pooled estimate; the state-space counterfactual, double
ML and causal forest (Phase 2B); spillovers to neighbouring districts; the Kerala 2018 case
study beyond its place in the pooled flood estimate. Exploratory results are shown with
their intervals and without multiple-testing claims.

## 8. Deviations

Every change after signing goes to `docs/decision_log.md` with its date, its reason and
whether any outcome had been seen, and is listed in the methods appendix (Phase 5D).

## 9. Sign-off

| Name | Role | Agreed on | Notes |
| --- | --- | --- | --- |
| Aradhya Somani | Data, ML and econometrics (sole owner from 2026-11-14) | | |

To sign: fill in the date, confirm in Notes that no post-event credit or deposit figure has
been seen, commit, and tag the commit `prereg-v1`.
