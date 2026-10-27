# Dicționarul indicatorilor

Fiecare indicator al panelului bancă × trimestru, ce înseamnă, de unde se ia și la ce folosește în lucrare. Descrierile din tabele sunt în engleză, ca să poată fi preluate direct într-o anexă; explicațiile pe familii sunt în română. Aceeași listă este disponibilă în aplicație (fila Indicators) și în reports/indicators.csv.

Convenții: ratele sunt fracții (0,12 = 12%); sumele sunt probabil în milioane EUR (unitatea nu este declarată în fișierele primite); „derived” înseamnă calculat de aplicație din alte câmpuri.

## Identifier

Câmpuri care identifică banca și momentul. Nu intră în modele; servesc la legarea fișierelor, la filtrare și la agregare pe țări, ani sau ediții.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| lei | Legal Entity Identifier of the bank (20 characters). Formula: as reported; old LEIs mapped to the current LEI. | all files, column LEI_Code | Key of the panel; bank identity across years. | LEIs change over time: the crosswalk of TR_Metadata is applied. |
| bank_name | Name of the bank. | TR_Metadata, sheet Bank list | Readable labels in tables and charts. | Taken from the latest edition available. |
| country_bank | ISO code of the country of the bank (NSA). | all files, column NSA | Filtering and aggregation by country; selects the regulatory profile (EU or BNM). | Not an input of the models. |
| quarter | Reference quarter (e.g. 2020Q1 for 202003). Formula: Period converted to a calendar quarter. | column Period (YYYYMM) | Time axis; label horizon and trends are computed on it. | Editions cover only some quarters; gaps are not filled. |
| year | Calendar year of the quarter. Formula: quarter.year. | derived | Aggregation by year; time split. | - |
| edition | Edition (folder year_XXXX) the row comes from. Formula: as loaded. | folder name | Traceability; the latest edition wins on duplicates. | - |

## Quality

Indicator de calitate a datelor: arată de ce unele valori lipsesc. Lipsa nu este aleatorie: o bancă fără FINREP nu raportează deloc active, capitaluri proprii, profit sau credite, deci toți indicatorii care depind de ele sunt goi pentru ea.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| finrep_reported | Whether the bank reports FINREP (accounting) data. Formula: False if the value starts with No. | TR_Metadata, Bank list, column Finrep | Explains structural missing values (assets, equity, profit, loans, NPL). | 13 banks are flagged in the 2020 edition. |

## Capital (level)

Sume în valoare absolută (în milioane EUR, presupus). Nu se folosesc direct ca variabile ale modelelor, ci pentru calculul ratelor și pentru verificarea coerenței datelor (de exemplu Tier 1 = CET1 + AT1).

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| cet1_capital | Common Equity Tier 1 capital after deductions and transitional adjustments. | tr_oth, item 2020102 | Numerator of the CET1 ratio; consistency check. | Unit not stated in the files received; verify in the guide. |
| at1_capital | Additional Tier 1 capital. | tr_oth, item 2020128 | Consistency check: Tier 1 = CET1 + AT1. | - |
| tier1_capital | Tier 1 capital (transitional). | tr_oth, item 2020133 | Numerator of the Tier 1 ratio. | - |
| tier2_capital | Tier 2 capital. | tr_oth, item 2020134 | Total capital = Tier 1 + Tier 2. | - |
| rwa | Total risk exposure amount (risk-weighted assets). | tr_oth, item 2020138 | Denominator of all capital ratios; proxy of balance-sheet size and risk. | Equals item 2021107 in the 2020 files. |
| leverage_exposure | Total leverage ratio exposure measure. | tr_oth, item 2020903 | Denominator of the leverage ratio. | - |

## Capital

Rate de capital: cel mai important grup de indicatori. Intră în modele, în reperul bazat pe reguli (nivelurile de alertă 7%, 8,5% și 10,5%) și definesc evenimentul E1. Sunt stocate ca fracții (0,12 = 12%).

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| cet1_ratio | CET1 capital / risk exposure amount, transitional definition. Formula: cet1_capital / rwa (verified to 1e-10). | tr_oth, item 2020140 | Main solvency indicator: feature of the models, input of the rule benchmark (alert level 7%), basis of event E1. | Stored as a fraction, not as a percentage. |
| tier1_ratio | Tier 1 capital / risk exposure amount. Formula: tier1_capital / rwa. | tr_oth, item 2020141 | Feature; rule benchmark (alert level 8.5%); event E1. | Highly correlated with CET1 ratio: check VIF for logistic regression. |
| total_capital_ratio | Total own funds / risk exposure amount. Formula: (cet1 + at1 + t2) / rwa. | tr_oth, item 2020142 | Feature; rule benchmark (alert level 10.5%); event E1. | Nested with the other two ratios. |
| cet1_ratio_fully_loaded | CET1 ratio without transitional arrangements. | tr_oth, item 2020146 | Sensitivity analysis; shows the effect of transitional rules. | Not used as primary feature. |
| leverage_ratio | Tier 1 capital (transitional) / total leverage exposure. | tr_oth, item 2020905 | Feature that does not depend on risk weights; complements the risk-based ratios. | Very high for some specialised banks; in 2020 no binding minimum applied in the EU. |

## Balance sheet

Mărimi contabile folosite ca control de dimensiune și ca numitori pentru alți indicatori.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| total_assets | Total assets (accounting). | tr_oth, item 2021010 | Size control; denominator checks. | Missing for banks without FINREP. |
| total_equity | Total accounting equity. | tr_oth, item 2021216 | Denominator of ROE. | Item missing in the SDD: resolved by exact label. |

## Earnings (level)

Profitul cumulat de la începutul anului fiscal și numărul de trimestre incluse; permit anualizarea profitului.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| net_profit_ytd | Profit or loss for the year, cumulated since the start of the bank's financial year. | tr_oth, item 2020335 | Numerator of ROE. | Year-to-date: March holds one quarter, June two. |
| pl_n_quarters | Number of quarters included in the year-to-date profit. | tr_oth, column n_quarters | Annualisation of the profit. | Differs for banks with a non-December year end. |

## Earnings

Profitabilitatea, componenta „E” din CAMELS. Împreună cu capitalul, este familia care ar trebui să apară pe primele două locuri în importanța SHAP (ipoteza H5).

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| roe_annualised | Return on equity, annualised. Formula: net_profit_ytd x (4 / pl_n_quarters) / total_equity. | derived | Earnings component of CAMELS; feature; one of the two families expected to rank first by SHAP (H5). | Volatile for small equity; flagged outliers kept. |

## Asset quality (level)

Sume de credite brute, neperformante și de Stage 3; servesc la calculul ratelor de calitate a activelor și la verificări încrucișate între șabloane.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| loans_gross | Gross carrying amount of loans and advances (amortised cost and fair value). | tr_cre, item 2020603, all breakdown dimensions at 0, Perf_Status 0 | Denominator of the NPL ratio; base of loan growth. | 123 of 135 banks report the NPE template. |
| npl_gross | Gross carrying amount of non-performing loans and advances. | tr_cre, item 2020603, Perf_Status 2 | Numerator of the NPL ratio. | - |
| npe_stage3 | Stage 3 loans as reported in the NPE template. | tr_cre, item 2020603, Perf_Status 23 | Cross-check with the Assets template. | Differs from tr_oth for 9 of 122 bank-quarters in 2020. |
| stage3_assets | Stage 3 loans as reported in the Assets template. | tr_oth, item 2021019, ASSETS_Stages 3 | Cross-check with npe_stage3. | - |

## Asset quality

Calitatea activelor, componenta „A” din CAMELS. Rata creditelor neperformante și ponderea Stage 2 sunt variabile ale modelelor, iar rata NPL este baza evenimentului E3.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| npl_ratio | Non-performing loans / total loans. Formula: npl_gross / loans_gross. | derived | Asset-quality feature; basis of event E3. | Up to 47% for Greek banks in 2020; heavy right tail. |
| stage2_share | Share of IFRS 9 Stage 2 loans in loans at amortised cost. Formula: S2 / (S1 + S2 + S3). | tr_oth, item 2021019, dimension ASSETS_Stages | Early signal of deterioration before loans become non-performing. | Only for banks reporting FINREP. |

## Concentration

Aproximări ale concentrării expunerilor. Expunerea pe client individual nu este publică în aceste date, deci concentrarea se măsoară prin indicele Herfindahl–Hirschman (suma pătratelor ponderilor), pe sectoare NACE și, când fișierul tr_sov este disponibil, pe țări emitente.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| nace_hhi | Herfindahl-Hirschman index of loans to non-financial corporations across NACE sectors. Formula: sum over sectors of (share of sector)^2. | tr_cre, item 2021301, NACE_codes 1-19, Perf_Status 0 | Proxy of sectoral concentration (the exposure per client is not public). | 1 means a single sector; undefined without loans. |
| sovereign_hhi | Herfindahl-Hirschman index of sovereign exposures across issuer countries. Formula: sum over countries of (share)^2. | tr_sov | Proxy of sovereign concentration. | Not computed yet: tr_sov not provided. |

## Trend

Variații față de trimestrul anterior sau față de același trimestru al anului precedent; se calculează doar dacă acel trimestru există în date. Sunt variabilele testate în ipoteza H3 (valoarea indicatorilor de tendință).

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| npl_delta_qoq | Change of the NPL ratio versus the previous quarter. Formula: npl_ratio(t) - npl_ratio(t-1). | derived | Trend feature tested in H3. | Empty unless the previous quarter exists. |
| loan_growth_qoq | Quarterly growth of gross loans. Formula: loans(t) / loans(t-1) - 1. | derived | Trend feature tested in H3 (credit growth). | Empty unless the previous quarter exists. |
| loan_growth_yoy | Annual growth of gross loans. Formula: loans(t) / loans(t-4) - 1. | derived | Trend feature tested in H3. | Needs editions covering four quarters earlier. |
| cet1_delta_qoq | Change of the CET1 ratio versus the previous quarter. Formula: cet1_ratio(t) - cet1_ratio(t-1). | derived | Capital trend; basis of event E2. | - |

## Distance to alert level

Distanța față de nivelurile de alertă ale evenimentului E1. Valoarea negativă înseamnă încălcare. Se folosește la reglarea marjei m a reperului R1 și pentru a vedea cât de aproape sunt băncile de un eveniment.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| cet1_headroom | Distance of the CET1 ratio from the E1 alert level. Formula: cet1_ratio - 0.07. | derived | Shows how far a bank is from event E1; used to tune the margin m of benchmark R1. | Alert levels are uniform, not bank-specific. |
| tier1_headroom | Distance of the Tier 1 ratio from its alert level. Formula: tier1_ratio - 0.085. | derived | Same use as above. | - |
| total_capital_headroom | Distance of the total capital ratio from its alert level. Formula: total_capital_ratio - 0.105. | derived | Same use as above. | - |
| min_headroom | Smallest of the three headrooms. Formula: min(cet1, tier1, total headroom). | derived | Single measure of proximity to a breach; negative means a breach. | - |

## Liquidity

Componenta „L” din CAMELS. Nu există în ediția 2020; se adaugă când ediții ulterioare o raportează.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| lcr | Liquidity coverage ratio. | tr_oth key metrics (later editions) | Liquidity component of CAMELS. | Not present in the 2020 edition. |

## Label

Variabile construite pentru învățarea supervizată: eșantionul de predicție și ținta.

| Indicator | Definition and formula | Source | Use | Caution |
|---|---|---|---|---|
| compliant_at_t | All three capital ratios are at or above their alert levels at t. Formula: ratios >= alert levels. | derived | Defines the prediction sample (new breaches only). | - |
| y_e1 | 1 if a breach of an alert level occurs in the next 4 quarters; 0 if the whole horizon is observed without breach; missing otherwise. Formula: see labels.py. | derived | Target of the supervised models and of the rule benchmark comparison. | Missing when the horizon is not fully observed. |

## Legătura cu ipotezele

| Hypothesis | Indicators involved | Role |
|---|---|---|
| H1a, H1b | all features of the capital, asset quality, earnings and concentration families | Inputs of logistic regression, Random Forest and XGBoost; capital ratios and alert levels also drive the rule benchmark |
| H2 | cet1_ratio, tier1_ratio, total_capital_ratio, min_headroom | First model alert vs. first breach of an alert level (lead time) |
| H3 | npl_delta_qoq, loan_growth_qoq, loan_growth_yoy, cet1_delta_qoq | Trend features compared with levels only |
| H4 | cet1_ratio, tier1_ratio, total_capital_ratio and the alert levels | Rule benchmark executed with a different configuration (BNM profile) |
| H5 | families Capital, Earnings, Asset quality, Concentration, Liquidity | Grouped SHAP importance per family |
