# Phase 0 A: RBI district data audit

Owner: Aradhya Somani (from Devna Roopesh, 2026-10-25) · Reviewer: Devna Roopesh · Status: **filled from the downloads of 2026-10-25.** Three quarters of 2016-17 and the non-March quarters from 2023 are not available to us and are excluded

This file answers one question for the Phase 0 gate: can we get district-level credit and deposits for a continuous span of at least 10 years? Everything below is filled from the files downloaded, not from memory. The numbers from the quarterly files come from `python scripts/rbi_first_look.py --out docs/00_rbi_first_look.md`.

**Short answer (2026-10-25): yes.** The BSR-7 quarterly statements give district deposits and credit for every quarter from March 2004 to June 2016 and from June 2017 to December 2022, 73 quarters, all banks including RRBs, in ₹ crore. That is 12 continuous years before the gap and five and a half after it. Two pieces are not available: September 2016 to March 2017 (three quarters), and the June, September and December quarters from 2023. DBIE asks for a login to download them and offers no sign-up, so they are excluded (decision of 2026-10-25, `docs/decision_log.md`). The annual BSR volumes add district credit every March from 2002 to 2026.

Only coverage, units, counts and all-India totals were computed. No district's credit or deposits around an event were looked at, so the pre-registration (`docs/00_hypotheses.md`) is still written blind.

## 1. What RBI says it publishes (from press releases, checked 2026-10-23)

| Fact | Source |
| --- | --- |
| The quarterly statistics on deposits and credit of scheduled commercial banks are "classified by states/union territories (UTs), districts, centres, population groups and bank groups" and published on DBIE. In March 2021 they were collected "from all SCBs (including Regional Rural Banks and Small Finance Banks)" under BSR-7. | [RBI press release, 28 May 2021](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=51647) |
| The June 2023 quarterly BSR-1 release covers 89 scheduled commercial banks excluding regional rural banks. It notes that BSR-7 was discontinued after the December 2022 reporting period, and that BSR-7-based tables are now generated from BSR-1 and BSR-2. | [RBI press release, June 2023 BSR-1](https://website.rbi.org.in/web/rbi/-/press-releases/quarterly-bsr-1-outstanding-credit-of-scheduled-commercial-banks-june-2023-56294) (as quoted in the task list; re-open it to confirm) |
| The annual BSR-2 release for March 2024 covers SCBs including RRBs and releases deposits by district, among other splits. Its data "include the impact of merger of a non-bank with a bank with effect from July 1, 2023". | [RBI press release, BSR-2 March 2024](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=58037) |
| Population groups are based on the Census 2011 population of the centre: rural below 10,000, semi-urban 10,000 to under 1 lakh, urban 1 lakh to under 10 lakh, metropolitan 10 lakh and above. | same as above |

Checked again on 2026-10-25 against the latest releases (DBIE has moved from dbie.rbi.org.in to https://data.rbi.org.in; the releases point to *Homepage > Publications* there):

| Fact | Source |
| --- | --- |
| Quarterly BSR-2 (deposits), December 2025: SCBs "excluding regional rural banks" report quarterly branch-wise deposits, and the data "are released at disaggregated level across population groups, bank groups, states, districts, and centres". Footnote: the data "include the impact of merger of a non-bank with a bank with effect from July 1, 2023". | [RBI press release, 27 Feb 2026](https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=62302); same wording for September 2025 ([28 Nov 2025](https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=61698)) |
| Quarterly BSR-1 (credit), December 2025: data reported by SCBs "{excluding Regional Rural Banks (RRBs)}" are "presented across bank groups, population groups and States". **Districts are not mentioned.** Growth figures from September 2023 to June 2024 are "calculated by adjusting merger of a non-bank with bank". | [RBI press release, 27 Feb 2026](https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=62304); same for June 2025 ([29 Aug 2025](https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=61115)) |
| Annual BSR-1 (credit), March 2025: covers SCBs including RRBs and collects the "district and population group of the place of utilisation of credit". | Release of 31 May 2025 (as reported by [hellobanker.in](https://hellobanker.in/?p=54348); open the RBI release to confirm) |
| RBI's Handbook table on deposits and credit by population group states credit "as per place of utilisation", amounts in ₹ crore. | [Handbook of Statistics, table 47](https://rbi.org.in/ScriptS/PublicationsView.aspx?id=23872) |

What this means for the audit, to be confirmed on the downloads:

- **Check that quarterly district credit continues after December 2022.** The quarterly BSR-1 release lists states, not districts, while the quarterly BSR-2 release lists districts. DBIE's "Quarterly Spatial Distribution of Deposits and Credit" (latest release June 2026) should carry both by district; if its credit stops at December 2022, the quarterly panel has district credit up to then and annual (March) district credit after. The main events end with Amphan (2020 Q2), whose 12-quarter window ends in 2023 Q2, so this would touch only the last few quarters of one window.
- **Coverage changes twice.** BSR-7 to December 2022 includes RRBs and small finance banks; the quarterly BSR-1 and BSR-2 releases from 2023 exclude RRBs. The rural districts where RRBs lend most will show a level drop in 2023 Q1 unless RBI back-casts.
- **Place of utilisation, not booking branch**, for the annual BSR-1 credit. This matters for the location-basis test (Phase 0 B): record which basis each downloaded table uses.

Coverage therefore differs between releases (with or without RRBs), and the source return changes at the end of 2022. Both are possible series breaks; section 5 checks them.

## 2. Where the tables are on DBIE

What to look for on https://data.rbi.org.in (step-by-step instructions are in `docs/data_cards/rbi.md`):

1. *Publications*, "Quarterly Spatial Distribution of Deposits and Credit": deposits, credit and offices by district each quarter, the panel's source. It has three entries (seen 2026-10-25): BSR-7 tables with RRBs for March 2004 to March 2017 and for June 2017 to December 2022, and "Spatial Distribution of Deposits and Credit - (Excluding Regional Rural Banks)" after that. Check that the last one still has district credit.
2. *Publications*, "Annual Spatial Distribution of Deposits and Credit - (Including Regional Rural Banks)" and "Annual Basic Statistical Return (BSR)-1 on Credit by Scheduled Commercial Banks - (Including Regional Rural Banks)": March figures with RRBs, and credit by occupation and place of utilisation.
3. *Publications*, "Bank Branch Statistics": branches by bank and district, for Phase 0 C.

What was downloaded on 2026-10-25 (file list and checksums in `docs/data_cards/rbi.md`):

- [x] Menu path: *data.rbi.org.in → Publications → Time-Series Publications*, then the publication by name.
- [x] **Annual BSR volumes**, "Basic Statistical Returns of Scheduled Commercial Banks in India", Vol 31 (March 2002) to Vol 54 (March 2025), one zip per year, plus the loose tables of the March 2026 release ("Outstanding Credit of Scheduled Commercial Banks in India", which replaced the volume). The district tables in them:
  - Table 2.4 (2002 to 2018), "District and population group-wise deposits and credit": offices, accounts, deposits and credit by district and population group, credit **by place of sanction**. From 2019 it becomes Table 2.14, credit only (deposits moved to the separate BSR-2 publication).
  - Table 5.9 (2002 to 2018), then Table 3.9 (2019 to 2026), "District-wise classification of outstanding credit according to occupation": accounts and credit by district and occupation (agriculture, industry, services, personal loans and so on), **by place of utilisation**.
  - Table 1.14 (new in 2026): district credit to individuals by gender, by place of sanction.
- [x] **"Spatial Distribution of Deposits and Credit (Excluding RRBs)"**, the series after BSR-7: Statements 1 to 6B, including Statement 4A (offices, deposits and credit by district) and 4B (deposits by type and district). The download has March 2023 to March 2026 only, one column block per March.
- [x] **BSR-7 "Quarterly Statistics on Deposits and Credit of SCBs"**, both entries, Statements 1 to 6B. Statement 4A of the first entry runs from March 2004 to **June 2016**, 50 quarters, although the entry's title says March 2017; the second runs from June 2017 to December 2022, 23 quarters. Several periods come in one download, one column block per quarter.
- [x] Not available: September 2016, December 2016 and March 2017, and Statement 4A of the 2023 onwards entry for June, September and December (its Statement 1 lists all 14 quarters, March 2023 to June 2026). Both downloads ask for a DBIE login, and DBIE has no sign-up. Excluded; March 2017 exists in the annual volume (Vol 46) on another basis and is not spliced in.
- [x] Bank-group split at district level: not in any district table downloaded so far (bank group appears only with state or population group). Occupation (sector) split: yes, annual only (Table 5.9 / 3.9).

## 3. Coverage

| Item | Annual BSR volumes (Tables 2.4/2.14, 5.9/3.9) | Statement 4A, 2023 onwards | BSR-7 quarterly Statement 4A, 2004 to 2022 |
| --- | --- | --- | --- |
| First period | March 2002 | March 2023 | March 2004 |
| Last period | March 2026 | March 2026 | December 2022 |
| Periods missing inside the span | none for credit; **deposits missing March 2019 to March 2022** (Table 2.14 has credit only, and the BSR-2 deposits publication for those years is not downloaded) | June, September and December of every year (behind a login, excluded) | September 2016, December 2016, March 2017 (behind a login, excluded) |
| Districts with figures | 575 (2002), 624 (2010), 698 (2018), 728 (2022), 775 (2025) | 739 (March 2023) to 754 (March 2026), out of 767 listed | 582 (2004), 621 (2009), 660 (June 2016), 701 (December 2019), 739 (December 2022) |
| Unit in the files | changes: Table 2.4 in ₹ lakh to 2010, ₹ million 2011 to 2017, ₹ crore from 2018; Table 5.9/3.9 in ₹ thousand from 2011 (₹ crore in 2018), ₹ lakh in 2005 and 2006, and not stated in the first rows in 2003, 2004 and 2007 to 2010 (check the volume PDF) | ₹ crore | ₹ crore |
| Banks covered | All scheduled commercial banks including RRBs. "These data are collected through Basic Statistical Return (BSR)-1 from the SCBs in India including the Regional Rural Banks (RRBs) annually" (Notes on Tables, 2026) | March columns include RRBs: "Regional Rural Banks will get covered only in annual publications from March 2023 round onwards" (BSR7 Notes on Tables); Statement 1 lists 121 banks covered in March 2026, of which 28 RRBs | All SCBs including RRBs: the five bank groups include "(iv) Regional Rural Banks" (BSR7 Notes on Tables, 2017 to 2022 entry) |
| Bank-group split at district level? | No | No | No |
| Credit by occupation at district level? | Yes, every year (Table 5.9/3.9) | No | No |
| Number of offices given? | Yes (Table 2.4/2.14) | Yes | Yes |
| Small districts | No rule stated in the 2026 notes | "district-wise/ centre-wise data are presented in respect of the Districts/ Centres having three or more branches/ offices" (BSR7 Notes on Tables); 5 to 28 of the 767 listed districts are blank in each March | same rule; 6.8% of all district-quarter amounts are blank |

The quarterly statements label each district with today's state (Telangana's 10 districts appear from 2004) but keep the district list of the quarter, so new districts appear when they were created. Reference date: the last reporting Friday for June, September and December quarters until June 2016, the last day of the quarter since September 2016; March is always 31 March.

District counts for the annual volumes come from a rough scratch parse of Table 2.4/2.14; they leave out single-district territories such as Delhi and Chandigarh, whose district row has the state's name. The Phase 1 C reader has to handle those.

## 4. Test states: Kerala, Odisha, Tamil Nadu

At least 10 years for each. Counts below are districts with figures in the annual Table 2.4/2.14. The per-district plots (`rbi_first_look.py --plots`) wait until the pre-registration is signed, because their lines run through the Kerala, Phailin, Hudhud, Chennai and Fani windows.

- [x] Kerala: 14 districts in every March from 2002 to 2026. Spellings differ from Census 2011 ("Alapuzha", "Cannur" in 2002, "Kannur" later). 25 years annual.
- [x] Odisha: 30 districts in every March from 2002 to 2026 (state named "Orissa" until 2011). 25 years annual.
- [x] Tamil Nadu: 30 districts (2002 to 2007), 31 (2008, 2009), 32 (2010 to 2021), 38 (2022 onward). The six districts created in 2019 and 2020 appear in RBI's tables only from March 2022, so RBI applies new boundaries with a lag of more than two years. The Phase 1 B crosswalk maps them back. 25 years annual.
- [x] Per quarter (BSR-7 and Statement 4A, March 2004 to March 2026): Kerala 14 and Odisha 30 in every quarter; Tamil Nadu 29 in 2004, then 30 from March 2005, 32 by June 2016 and 38 by December 2022. 73 quarters for each state, plus the 2016-17 gap.

## 5. Series breaks

Paste the "break check" table. A jump in the Dec 2022 to Mar 2023 change that is far larger than the median quarterly change suggests a break, not a real movement.

| Candidate break | What to check | Finding |
| --- | --- | --- |
| Definition of credit, September 2016 | Level shift in 2016 Q3 | BSR-7 moved from gross bank credit to bank credit, which leaves out "bills rediscounted with the RBI and other approved financial institutions" (BSR7 Notes on Tables). Cannot be measured: the three excluded quarters are exactly September 2016 to March 2017. All-India credit grows 8.0% from June 2016 to June 2017. The panel treats June 2016 to June 2017 as a break |
| Reference date and seasonality, September 2016 | Size of the March jump before and after | Until June 2016, June, September and December figures are for the last reporting Friday and March is 31 March, so the December to March change is large (all-India credit 7.1% to 11.4% each year, 2005 to 2016). From September 2016 every figure is for the last day of the quarter and the same change is 3.1% to 5.3%. The quarter-by-event fixed effects absorb this; a model with one seasonal pattern for all years does not |
| Census used for population groups | Shifts between rural, semi-urban, urban and metro, not in district totals | 1991 Census to December 2005, 2001 Census from March 2006 to June 2016, 2011 Census from September 2016. Cities spread over several districts (Chennai, Greater Hyderabad, Mumbai, Srinagar) are one centre from September 2016. Matters only for population-group splits |
| Units | A factor of 10 or 100 between years | Table 2.4 changes from lakh to million (2011) to crore (2018); the reader converts each file by its own title row |
| BSR-7 discontinued after Dec 2022; tables built from BSR-1/BSR-2 since | All-India and test-state growth in 2023 Q1 against the median | Confirmed by RBI: "quarterly reporting of BSR-7 by SCBs have been discontinued from March 2023 ... the BSR7 statements/tables will get populated from BSR-1 and BSR-2" (BSR7 Notes on Tables). No jump at all-India level: the December 2022 to March 2023 change is 4.3% for credit and 4.9% for deposits, inside the range of the same change in 2018 to 2022 (3.1% to 5.3% credit, 3.4% to 5.0% deposits). District level: cannot be checked without the 2023 quarters, which are excluded |
| Coverage with vs without RRBs between releases | Footnotes of the downloaded tables; level shift in rural districts | From March 2023, March figures include RRBs and the other quarters do not. RRBs are 2.8% of credit but 13.4% of offices nationally (Table 1.1, March 2026), so the gap is concentrated in rural districts. Annual series are not affected. Also: RRBs were amalgamated from 43 to 28 banks during 2025-26 (Statement 1); this changes bank counts, not district totals |
| Bank mergers (public sector bank mergers in April 2017, April 2019 and April 2020) | Bank-group totals jump between groups but not in the "all banks" total | No district table has a bank-group split, so this does not touch the panel. RBI notes the bank-group changes (SBI associates merged April 2017; IDBI Bank moved to private sector from March 2019; Lakshmi Vilas Bank into DBS, November 2020) |
| Merger of a non-bank with a bank, 1 July 2023 | Level shift in private-bank credit and deposits in 2023 Q3 | After every main event's window, except the last quarters of Amphan's. Not measurable from March figures alone; the 2023 quarters are excluded |
| District count changes | Districts per quarter jumps up in a state | Districts with figures rise from 575 (2002) to 775 (2025). Large steps: Andhra Pradesh 23 to 13 in 2015 (Telangana) and 13 to 26 in 2023 (2022 reorganisation); Tamil Nadu 32 to 38 in 2022; West Bengal 19 to 23 between 2016 and 2019. Every step needs the Phase 1 B crosswalk |

## 6. Verdict for the gate

- [x] District credit and deposits available for at least 10 continuous years? **Yes, quarterly**: March 2004 to June 2016 (50 quarters, 12 years) and June 2017 to December 2022 (23 quarters), all banks including RRBs, with a gap of three quarters that is not available. Annually: credit March 2002 to March 2026 (25 years).
- [x] Usable for the event study as is, with flagged breaks: **yes, at district level, not Fallback 1.** Every main event's window (8 quarters before, 12 after) falls inside March 2004 to June 2023: Kosi (2008 Q3) needs quarters from 2006 Q3, and Amphan's (2020 Q2) ends in 2023 Q2. The breaks to flag are the 2016-17 reference-date and credit-definition change and, for Amphan's last two quarters, RRBs leaving the non-March quarters in 2023. Without the 2016-17 quarters, Phailin's window (2013 Q4) misses quarters +11 and +12, Hudhud's (2014 Q4) +7 to +9, and Chennai's (2015 Q4) +3 to +5. **Chennai fails the draft pre-registration's rule** that every district has quarters −8 to +3; whether to drop it or relax the rule is open in `docs/00_hypotheses.md`.
- [x] Surprises, logged in `docs/data_cards/rbi.md`:
  - The annual volumes carry district credit on **both** bases every year: place of sanction (Table 2.4/2.14) and place of utilisation (Table 5.9/3.9). Phase 0 B can compare the two directly by district.
  - Units change between years and between tables.
  - RBI applies new district boundaries with a lag (Tamil Nadu's 2019 and 2020 districts appear in 2022).
  - District deposits for March 2019 to March 2022 are not in the BSR-1 volumes; they are in the separate BSR-2 publication of those years, or in the quarterly BSR-7 statements.
