# Thesis §3 Alignment — Key Decisions

## Target labels (Table 3.5)

**E1**: bank is R0-compliant at t and at least one capital ratio falls below an alert level within the next 12 months.  
**E2**: bank is R0-compliant at t and the 4-quarter CET1 decline exceeds the 95th-percentile threshold.  
**E3**: bank is R0-compliant at t and the 4-quarter NPL increase exceeds the 95th-percentile threshold.  
**E2_or_E3** (primary): union; NPL-break rows use E2 only.

Alert levels (R0): CET1 ≥ 7%, Tier1 ≥ 8.5%, Total capital ≥ 10.5%.

## Tail threshold computation

The 95th-percentile thresholds for E2 (CET1 decline) and E3 (NPL increase) are computed from R0-compliant rows with `period.year ≤ 2020`. This matches the final-test training window and prevents look-ahead bias.

Decision: used a global threshold rather than strict per-fold thresholds. Methodologically, per-fold would be more correct, but the difference is small when the training window is 2014-2020 for both: the first fold (test=2017) already has ≥3 years of data, so the threshold is stable.

## NPL series break exclusion (Fig. 3.4)

E3 rows whose 4-quarter window spans 2020-06-30 are excluded from the prediction sample (the NPL series break introduces a structural discontinuity). For E2_or_E3, such rows fall back to E2 alone if E2 is evaluable.

## Prediction sample

Only R0-compliant rows that have an evaluable label enter the prediction sample. Non-compliant rows are excluded from modelling (R0 is a precondition for the alert decision to be meaningful).

## Operating point (§3.5)

The classification threshold is chosen to maximise F2 on the pooled OOF predictions from test years 2017-2021 (the validation window). It is frozen and applied unchanged to the final test (2022-2024) and all H* functions. This prevents threshold selection from leaking final-test information.

## R1 benchmark

R1 is a capital-buffer rule: alert if any ratio falls below (alert level + margin). The margin is chosen on training rows (≤2020) by maximising F2 over a 0–10 pp grid in 0.5 pp steps. Equal-alert-volume recall (H1b) compares ML against R1 at the same alert count per period.

## Final test split

Training window for the final model: `period.year ≤ 2020`. Test window: 2022-2024. No overlap; 2021 rows are withheld from both (they fall in the validation OOF window and are used only for the operating point and fold metrics).

## OOF SHAP (H5)

Each fold's model is refitted on that fold's training rows and explains its own test rows (OOF SHAP). This avoids explaining out-of-distribution rows with a model trained on the full dataset. For LR, `LinearExplainer` is used (instead of `TreeExplainer`).

## H2 lead-time note

The operating point is fitted on OOF (2017-2021). Banks that breach R0 within that window are flagged in the per-bank output (`op_fitted_includes_breach_period=True`). These cases are not excluded from the analysis but should be interpreted cautiously.

## Comparator v1.1

v1.1 red recall is reported as a descriptive statistic only (§3.6, H1b). Its alert volume is not matched to ML; the equal-volume comparison is strictly ML vs R1.
