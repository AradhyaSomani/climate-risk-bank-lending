# Phase 0 B: Location-basis test

Owner: Aradhya Somani · Reviewer: Devna Roopesh · Status: **B1 done on March 2007 data; B2 needs the state banker-committee figures; B3 proposed, to be agreed**

RBI's quarterly district tables put credit where the branch that books it is (place of sanction). A loan booked in Mumbai for a refinery in Jamnagar counts in Mumbai. The event study needs credit where the flood or cyclone hits, so this file checks how far the two differ.

The annual BSR volumes publish district credit on both bases every year (`docs/data_cards/rbi.md`):

- Table 2.4 (to 2018, then 2.14): deposits and credit by place of sanction;
- Table 5.9 (to 2018, then 3.9): credit by place of utilisation.

Accounts in BSR-1B (small loans) report no place of utilisation, and RBI assumes they are used where they are sanctioned (notes to the 2010 volume). The utilisation figures are therefore exact for large loans and equal to sanction for small ones.

**Data year: March 2007**, the last March before every main event (Kosi is August 2008), so no figure here is an outcome after an event. Reproduce with `python scripts/rbi_location_basis.py`; the district table is saved to `data/interim/rbi_location_basis_2007.csv`.

## B1. Credit-to-deposit ratio and the two bases, by district

- 606 districts matched between the two tables (all but Puducherry).
- Nationally the two bases agree, as they must: ₹19.46 lakh crore by sanction and ₹19.45 lakh crore by utilisation. The correlation of log district credit on the two bases is 0.97.
- But **154 of 606 districts (25%) differ by more than a factor of 1.25** between the bases.
- Credit is concentrated: the 10 largest districts hold 62% of all credit by sanction.

### Distribution

|     |   cd_ratio |   utilisation_over_sanction |
|:----|-----------:|----------------------------:|
| 5%  |       0.21 |                        0.85 |
| 25% |       0.35 |                        1    |
| 50% |       0.54 |                        1.05 |
| 75% |       0.75 |                        1.2  |
| 95% |       1.12 |                        2.51 |


### Largest districts by credit (sanction)

| state          | district        |   deposits_cr |   credit_sanction_cr |   credit_utilisation_cr |   cd_ratio |   utilisation_over_sanction |
|:---------------|:----------------|--------------:|---------------------:|------------------------:|-----------:|----------------------------:|
| MAHARASHTRA    | BRIHAN MUMBAI   |    532,563.63 |           551,531.39 |              403,157.29 |       1.04 |                        0.73 |
| DELHI          | Delhi           |    336,067.05 |           238,053.82 |              233,798.48 |       0.71 |                        0.98 |
| TAMIL NADU     | CHENNAI         |     78,246.23 |           101,722.47 |              104,204.50 |       1.30 |                        1.02 |
| KARNATAKA      | BANGALORE URBAN |    111,977.44 |            84,678.58 |              118,717.07 |       0.76 |                        1.40 |
| WEST BENGAL    | KOLKATA         |     84,483.04 |            74,474.18 |               76,523.30 |       0.88 |                        1.03 |
| ANDHRA PRADESH | HYDERABAD       |     54,365.26 |            54,376.80 |               60,727.60 |       1.00 |                        1.12 |
| GUJARAT        | AHMADABAD       |     31,670.05 |            30,772.58 |               31,579.77 |       0.97 |                        1.03 |
| MAHARASHTRA    | PUNE            |     39,298.34 |            29,516.52 |               32,249.70 |       0.75 |                        1.09 |
| TAMIL NADU     | COIMBATORE      |     16,142.25 |            27,219.80 |               27,159.92 |       1.69 |                        1.00 |
| PUNJAB         | LUDHIANA        |     14,670.08 |            20,198.64 |               17,074.39 |       1.38 |                        0.85 |


Brihan Mumbai books ₹1.48 lakh crore more than is used there (37% more), and Bangalore Urban uses 40% more than it books. Delhi, Chennai, Kolkata and Hyderabad are within 12%.

### Highest credit-deposit ratio

| state          | district      |   deposits_cr |   credit_sanction_cr |   credit_utilisation_cr |   cd_ratio |   utilisation_over_sanction |
|:---------------|:--------------|--------------:|---------------------:|------------------------:|-----------:|----------------------------:|
| MADHYA PRADESH | RAISEN        |        473.80 |               908.59 |                1,060.86 |       1.92 |                        1.17 |
| MANIPUR        | CHANDEL       |         20.14 |                36.07 |                   36.33 |       1.79 |                        1.01 |
| RAJASTHAN      | BHILWARA      |      1,557.22 |             2,667.25 |                3,453.44 |       1.71 |                        1.29 |
| TAMIL NADU     | COIMBATORE    |     16,142.25 |            27,219.80 |               27,159.92 |       1.69 |                        1.00 |
| MIZORAM        | SAIHA         |         20.34 |                34.08 |                   32.43 |       1.68 |                        0.95 |
| KERALA         | WAYANAD       |        577.87 |               884.35 |                  976.88 |       1.53 |                        1.10 |
| ANDHRA PRADESH | WEST GODAVARI |      3,441.87 |             4,962.09 |                4,357.16 |       1.44 |                        0.88 |
| TAMIL NADU     | VIRUDHUNAGAR  |      2,292.61 |             3,236.38 |                3,156.98 |       1.41 |                        0.98 |
| ANDHRA PRADESH | GUNTUR        |      4,852.00 |             6,691.77 |                5,952.97 |       1.38 |                        0.89 |
| PUNJAB         | LUDHIANA      |     14,670.08 |            20,198.64 |               17,074.39 |       1.38 |                        0.85 |

### Lowest credit-deposit ratio

| state             | district      |   deposits_cr |   credit_sanction_cr |   credit_utilisation_cr |   cd_ratio |   utilisation_over_sanction |
|:------------------|:--------------|--------------:|---------------------:|------------------------:|-----------:|----------------------------:|
| DAMAN & DIU       | DIU           |        444.71 |                18.18 |                   53.38 |       0.04 |                        2.94 |
| ANDAMAN & NICOBAR | NICOBAR       |         83.10 |                 6.97 |                    6.21 |       0.08 |                        0.89 |
| ARUNACHAL PRADESH | TAWANG        |         84.23 |                 8.32 |                   16.13 |       0.10 |                        1.94 |
| LAKSHADWEEP       | Lakshadweep   |        206.33 |                20.95 |                   51.06 |       0.10 |                        2.44 |
| JAMMU & KASHMIR   | KARGIL        |        229.54 |                27.28 |                   27.36 |       0.12 |                        1.00 |
| NAGALAND          | KOHIMA        |      1,035.38 |               126.47 |                  175.47 |       0.12 |                        1.39 |
| ARUNACHAL PRADESH | UPPER SIANG   |         38.89 |                 5.19 |                    5.19 |       0.13 |                        1.00 |
| GUJARAT           | NAVSARI       |      4,924.21 |               707.55 |                  836.32 |       0.14 |                        1.18 |
| MADHYA PRADESH    | SIDHI         |      1,987.77 |               311.91 |                  320.02 |       0.16 |                        1.03 |
| UTTARAKHAND       | TEHRI GARHWAL |        815.52 |               132.50 |                  157.78 |       0.16 |                        1.19 |

### Most credit used beyond what is booked (utilisation / sanction)

| state                | district            |   deposits_cr |   credit_sanction_cr |   credit_utilisation_cr |   cd_ratio |   utilisation_over_sanction |
|:---------------------|:--------------------|--------------:|---------------------:|------------------------:|-----------:|----------------------------:|
| GUJARAT              | DANGS               |        125.22 |                34.91 |                1,774.78 |       0.28 |                       50.84 |
| ARUNACHAL PRADESH    | CHUNGLANG           |         81.39 |                14.30 |                  238.99 |       0.18 |                       16.71 |
| ASSAM                | HAILAKANDI          |        217.18 |                77.92 |                  885.47 |       0.36 |                       11.36 |
| BIHAR                | GOPALGANJ           |      1,238.20 |               324.08 |                3,242.65 |       0.26 |                       10.01 |
| GUJARAT              | JAMNAGAR            |      4,052.53 |             1,387.64 |                9,872.43 |       0.34 |                        7.11 |
| MAHARASHTRA          | RATNAGIRI           |      1,814.53 |               794.24 |                4,625.75 |       0.44 |                        5.82 |
| UTTARAKHAND          | RUDRAPRAYAG         |        220.43 |                62.54 |                  360.64 |       0.28 |                        5.77 |
| UTTARAKHAND          | CHAMOLI             |        533.21 |               133.18 |                  761.11 |       0.25 |                        5.71 |
| DADRA & NAGAR HAVELI | DADRA & NAGAR HAVEL |        503.91 |               104.03 |                  586.33 |       0.21 |                        5.64 |
| HIMACHAL PRADESH     | KINNAUR             |        167.19 |                66.73 |                  353.66 |       0.40 |                        5.30 |

### Most credit booked beyond what is used

| state           | district                 |   deposits_cr |   credit_sanction_cr |   credit_utilisation_cr |   cd_ratio |   utilisation_over_sanction |
|:----------------|:-------------------------|--------------:|---------------------:|------------------------:|-----------:|----------------------------:|
| PUNJAB          | SAHIBZADA AJIT SING NAGA |      4,678.52 |             1,789.56 |                  429.75 |       0.38 |                        0.24 |
| ASSAM           | CHIRANG                  |        193.36 |               194.93 |                   60.22 |       1.01 |                        0.31 |
| JAMMU & KASHMIR | PULWAMA                  |        738.17 |               713.33 |                  290.21 |       0.97 |                        0.41 |
| PUNJAB          | BARNALA                  |        684.01 |               526.74 |                  224.40 |       0.77 |                        0.43 |
| JHARKHAND       | SERAIKELA-KHARSAWAN      |        776.43 |               409.55 |                  237.51 |       0.53 |                        0.58 |
| MANIPUR         | IMPHAL EAST              |         43.27 |                25.56 |                   15.33 |       0.59 |                        0.60 |
| MADHYA PRADESH  | BARWANI                  |        611.77 |               375.77 |                  242.31 |       0.61 |                        0.64 |
| CHHATTISGARH    | DHAMTARI                 |        499.17 |               236.85 |                  167.77 |       0.47 |                        0.71 |
| JAMMU & KASHMIR | KUPWARA                  |        479.49 |               170.30 |                  122.66 |       0.36 |                        0.72 |
| JAMMU & KASHMIR | UDHAMPUR                 |      1,108.70 |               418.91 |                  304.36 |       0.38 |                        0.73 |

## What the extremes are

- **High credit-deposit ratios** are probably districts with large industrial, trade or plantation lending: Coimbatore, Virudhunagar, Ludhiana, Bhilwara, the Godavari delta, Wayanad. Nothing suggests data errors.
- **Low ratios** are remote or remittance districts with deposits and little lending: Nicobar, Tawang, Kargil, Kohima, Navsari, Lakshadweep, Diu.
- **Credit used far beyond what is booked** is where a large project sits: Jamnagar (7.1 times, home to large refineries), Dangs (50.8 times, presumably a few very large accounts), Ratnagiri, the Uttarakhand hydro districts (Rudraprayag, Chamoli), Kinnaur. Rural districts of Bihar and Assam (Gopalganj, Purnia, Hailakandi) also use 4 to 10 times what they book. The likely reason is agricultural and priority-sector loans booked at a branch in a neighbouring district; this is a guess, not checked.
- **Credit booked far beyond what is used**: Mumbai, SAS Nagar (Mohali), Pulwama, Barnala, Chirang. These are district headquarters or towns whose branches lend into the surrounding districts.

## Main-event districts

Matching the treated districts of the six main events with hazard footprints (`event_district.parquet`) to the 2007 table by state and district name finds 59 of 75 (the rest are spelling differences, for the Phase 1 B crosswalk). **17 of the 59 are flagged**, almost all because more credit is used in them than booked: Kosi 6 of 17 (Araria 3.5 times, Khagaria 3.1, Katihar 2.7), Phailin 3 of 12 (Puri 2.45), Fani 5 of 15, Amphan 2 of 11 (Howrah, South 24 Parganas), Hudhud 1 of 3, Chennai 0 of 1.

So the booked figure understates the credit at stake in a hit rural district rather than overstating it. Leaving flagged districts out would remove a third of the Kosi districts.

## B2. Comparison with the state banker committee

- [ ] TODO: the State Level Bankers' Committee (SLBC) of Odisha or Kerala publishes district credit each quarter in its meeting papers. Take one quarter for one state, compare the district totals with Statement 4A, and record the agreement here. This needs a manual download from the SLBC site.

## B3. How metro and headquarters districts are handled (proposed, to agree with Devna before the pre-registration is signed)

1. **Keep every district in the main specification**, on the place-of-sanction quarterly series, which is the only quarterly series there is.
2. **Flag two groups** in the panel, both fixed from March 2007 data so the flag cannot respond to an event:
   - `metro_hq`: the six largest credit centres (Brihan Mumbai, Delhi, Chennai, Bangalore Urban, Kolkata, Hyderabad), which hold 57% of credit by sanction;
   - `basis_gap`: the 154 districts whose two bases differ by more than a factor of 1.25.
3. **Robustness checks**:
   - drop `metro_hq` districts (as treated and as controls), as the pre-registration's open item proposes. Chennai would then leave its own event, so the Chennai result is reported with and without it;
   - drop `basis_gap` districts;
   - re-estimate the effect on credit with the annual March series by place of utilisation (Table 5.9 / 3.9), event time in years. This is the only check where credit is counted where it is used.
4. Write the chosen rule into section 4 of `docs/00_hypotheses.md` in place of "open" before signing.

Caveats: the numbers come from one year and one parse of the 2007 tables; the Phase 1 C reader for the annual volumes will recompute them. Name matching here is by spelling only.
