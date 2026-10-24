# Phase 0 A: RBI district data audit

Owner: Devna Roopesh (Person B) · Reviewer: Aradhya Somani · Status: **template, to be filled from the real downloads**

This file answers one question for the Phase 0 gate: can we get district-level credit and deposits for a continuous span of at least 10 years? Fill every `TODO` from the files you downloaded, not from memory. Paste the output of `python scripts/rbi_first_look.py` where marked.

## 1. What RBI says it publishes (from press releases, checked 2026-10-23)

| Fact | Source |
| --- | --- |
| The quarterly statistics on deposits and credit of scheduled commercial banks are "classified by states/union territories (UTs), districts, centres, population groups and bank groups" and published on DBIE. In March 2021 they were collected "from all SCBs (including Regional Rural Banks and Small Finance Banks)" under BSR-7. | [RBI press release, 28 May 2021](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=51647) |
| The June 2023 quarterly BSR-1 release covers 89 scheduled commercial banks excluding regional rural banks. It notes that BSR-7 was discontinued after the December 2022 reporting period, and that BSR-7-based tables are now generated from BSR-1 and BSR-2. | [RBI press release, June 2023 BSR-1](https://website.rbi.org.in/web/rbi/-/press-releases/quarterly-bsr-1-outstanding-credit-of-scheduled-commercial-banks-june-2023-56294) (as quoted in the task list; re-open it to confirm) |
| The annual BSR-2 release for March 2024 covers SCBs including RRBs and releases deposits by district, among other splits. Its data "include the impact of merger of a non-bank with a bank with effect from July 1, 2023". | [RBI press release, BSR-2 March 2024](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=58037) |
| Population groups are based on the Census 2011 population of the centre: rural below 10,000, semi-urban 10,000 to under 1 lakh, urban 1 lakh to under 10 lakh, metropolitan 10 lakh and above. | same as above |

Coverage therefore differs between releases (with or without RRBs), and the source return changes at the end of 2022. Both are possible series breaks; section 5 checks them.

## 2. Where the tables are on DBIE

- [ ] TODO: exact menu path or URL of the district-wise deposits and credit table you used (for example *DBIE → Statistics → Banking → …*).
- [ ] TODO: table name(s) as DBIE shows them.
- [ ] TODO: can you choose several quarters in one download, or is it one file per quarter?
- [ ] TODO: is there a separate district table by **bank group**? By **occupation/sector** of credit? (If sector is only annual, note the table name and frequency.)

## 3. Coverage

Paste the first block of `rbi_first_look.py` output here.

| Item | Value |
| --- | --- |
| First quarter available | TODO |
| Last quarter available | TODO |
| Quarters missing inside the span | TODO |
| Districts per quarter (first year, last year) | TODO |
| Unit in the files (lakh or crore) | TODO |
| Banks covered (with or without RRBs, SFBs, payments banks) | TODO, quote the table footnote |
| Bank-group split at district level? | TODO yes/no, list the groups |
| Credit split by occupation or sector at district level? | TODO yes/no, frequency |
| Number of offices given? | TODO |

## 4. Test states: Kerala, Odisha, Tamil Nadu

At least 10 years for each. Paste the "Districts reporting per quarter" table and look at `docs/figures/00_rbi_*.png`.

- [ ] Kerala: TODO (districts: expect 14; years covered; anything odd)
- [ ] Odisha: TODO (expect 30)
- [ ] Tamil Nadu: TODO (32 in Census 2011; new districts from 2019 onward will show up as extra names. Record them; the crosswalk in Phase 1 B maps them back)

## 5. Series breaks

Paste the "break check" table. A jump in the Dec 2022 to Mar 2023 change that is far larger than the median quarterly change suggests a break, not a real movement.

| Candidate break | What to check | Finding |
| --- | --- | --- |
| BSR-7 discontinued after Dec 2022; tables built from BSR-1/BSR-2 since | All-India and test-state growth in 2023 Q1 against the median | TODO |
| Coverage with vs without RRBs between releases | Footnotes of the downloaded tables; level shift in rural districts | TODO |
| Bank mergers (public sector bank mergers in April 2017, April 2019 and April 2020) | Bank-group totals jump between groups but not in the "all banks" total | TODO |
| Merger of a non-bank with a bank, 1 July 2023 | Level shift in private-bank credit and deposits in 2023 Q3 | TODO |
| District count changes | Districts per quarter jumps up in a state | TODO |

## 6. Verdict for the gate

- [ ] District credit and deposits available for at least 10 continuous years? TODO yes/no, span
- [ ] Usable for the event study as is, with flagged breaks, or only at state level (Fallback 1)? TODO
- [ ] Surprises to log in `docs/data_cards/rbi.md`: TODO
