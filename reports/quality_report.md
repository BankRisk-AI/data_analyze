# Quality report

## Checks

| check                                                     | status    | detail                                              |
|:----------------------------------------------------------|:----------|:----------------------------------------------------|
| unique key (bank, quarter)                                | OK        | 266 rows                                            |
| CET1 ratio = CET1 capital / RWA                           | OK        | max abs diff 4.94e-11 on 266 rows                   |
| Tier 1 = CET1 + AT1                                       | OK        | max abs diff 2.18e-10                               |
| Total ratio = (CET1 + AT1 + T2) / RWA                     | OK        | max abs diff 4.98e-11                               |
| Stage 3 loans: tr_oth (Assets) vs tr_cre (NPE)            | ATTENTION | 92.2% of 122 bank-quarters agree to 1e-6 (relative) |
| ratios stored as fractions                                | OK        | median CET1 ratio = 0.1586                          |
| CET1 ratio > 50% (public-development / specialised banks) | ATTENTION | 4 banks flagged (kept, marked for review)           |

## Missing values

|                     |   missing |   share |   missing_among_no_FINREP_banks |   n_no_FINREP_rows |
|:--------------------|----------:|--------:|--------------------------------:|-------------------:|
| cet1_ratio          |         0 |   0     |                               0 |                 25 |
| tier1_ratio         |         0 |   0     |                               0 |                 25 |
| total_capital_ratio |         0 |   0     |                               0 |                 25 |
| leverage_ratio      |         0 |   0     |                               0 |                 25 |
| npl_ratio           |        25 |   0.094 |                              25 |                 25 |
| roe_annualised      |        25 |   0.094 |                              25 |                 25 |
| nace_hhi            |        27 |   0.102 |                              25 |                 25 |
| loan_growth_qoq     |       147 |   0.553 |                              25 |                 25 |
| loan_growth_yoy     |       266 |   1     |                              25 |                 25 |
| npl_delta_qoq       |       147 |   0.553 |                              25 |                 25 |

## Panel balance

| quarter   |   banks |   entering |   last_seen |
|:----------|--------:|-----------:|------------:|
| 2020Q1    |     131 |        131 |           0 |
| 2020Q2    |     135 |          4 |         135 |

## Cross-sectional outlier flags (IQR x 3): 41

| quarter   | indicator      | lei                  |     value |
|:----------|:---------------|:---------------------|----------:|
| 2020Q1    | cet1_ratio     | 213800EUDXECGWMKKR98 |  0.46995  |
| 2020Q1    | cet1_ratio     | 529900HEKOENJHPNN480 |  0.78068  |
| 2020Q1    | cet1_ratio     | 529900V3O1M5IHMOSF46 |  0.332236 |
| 2020Q1    | cet1_ratio     | 549300XFX12G42QIKN82 |  0.319314 |
| 2020Q1    | cet1_ratio     | EV2XZWMLLXF2QRX0CD47 |  1.40636  |
| 2020Q1    | cet1_ratio     | MMYX0N4ZEZ13Z4XCG897 |  0.478453 |
| 2020Q1    | cet1_ratio     | R1IO4YJ0O79SMWVCHB58 |  0.40286  |
| 2020Q2    | cet1_ratio     | 213800EUDXECGWMKKR98 |  0.527538 |
| 2020Q2    | cet1_ratio     | 529900HEKOENJHPNN480 |  0.877595 |
| 2020Q2    | cet1_ratio     | 529900V3O1M5IHMOSF46 |  0.359733 |
| 2020Q2    | cet1_ratio     | EV2XZWMLLXF2QRX0CD47 |  1.55495  |
| 2020Q2    | cet1_ratio     | JLP5FSPH9WPSHY3NIM24 |  0.463547 |
| 2020Q2    | cet1_ratio     | MMYX0N4ZEZ13Z4XCG897 |  0.5894   |
| 2020Q1    | npl_ratio      | 5299009N55YRQC69CN08 |  0.381468 |
| 2020Q1    | npl_ratio      | 549300UY81ESCZJ0GR95 |  0.190515 |
| 2020Q1    | npl_ratio      | 5UMCZOEYKCVFAW8ZLO05 |  0.247662 |
| 2020Q1    | npl_ratio      | 635400L14KNHZXPUZM19 |  0.200609 |
| 2020Q1    | npl_ratio      | CXUHEGU3MADZ2CEV7C11 |  0.200742 |
| 2020Q1    | npl_ratio      | JEUVK5RWVJEN8W0C9M24 |  0.251552 |
| 2020Q1    | npl_ratio      | M6AD1Y1KW32H8THQ6F76 |  0.459099 |
| 2020Q2    | npl_ratio      | 5299009N55YRQC69CN08 |  0.434699 |
| 2020Q2    | npl_ratio      | 549300UY81ESCZJ0GR95 |  0.241794 |
| 2020Q2    | npl_ratio      | 5UMCZOEYKCVFAW8ZLO05 |  0.274119 |
| 2020Q2    | npl_ratio      | 635400L14KNHZXPUZM19 |  0.20932  |
| 2020Q2    | npl_ratio      | CXUHEGU3MADZ2CEV7C11 |  0.251208 |
| 2020Q2    | npl_ratio      | JEUVK5RWVJEN8W0C9M24 |  0.147889 |
| 2020Q2    | npl_ratio      | M6AD1Y1KW32H8THQ6F76 |  0.474742 |
| 2020Q1    | roe_annualised | 222100ZXZ9BRGDMKXL75 |  0.804194 |
| 2020Q1    | roe_annualised | 96950066U5XAAIRCPA78 |  0.894854 |
| 2020Q1    | roe_annualised | D3K6HXMBBB6SK9OXH394 | -0.518638 |
| 2020Q2    | roe_annualised | 2138009Y59EAR7H1UO97 | -0.185472 |
| 2020Q2    | roe_annualised | 213800TC9PZRBHMJW403 | -0.352132 |
| 2020Q2    | roe_annualised | 222100K6QL2V4MLHWQ08 | -0.317695 |
| 2020Q2    | roe_annualised | 222100ZXZ9BRGDMKXL75 |  0.395735 |
| 2020Q2    | roe_annualised | 5493006QMFDDMYWIAM13 | -0.225169 |
| 2020Q2    | roe_annualised | 635400C8EK6DRI12LJ39 | -0.145807 |
| 2020Q2    | roe_annualised | 635400L14KNHZXPUZM19 | -0.149235 |
| 2020Q2    | roe_annualised | 96950066U5XAAIRCPA78 |  0.431161 |
| 2020Q2    | roe_annualised | D3K6HXMBBB6SK9OXH394 | -0.239022 |
| 2020Q2    | roe_annualised | J4CP7MHCXR8DAQMKIL78 | -0.304139 |

## Decision log

- [2020] item column of the SDD used for this edition: Item
- [2020] item 2021216 resolved by label match (item missing in SDD) -> 2021216
