# T-3 Sensitivity Analysis Results: EBA ML Stage §3.6

Run date: 2026-11-25 · Seed: 20261121 · Primary label: E2\_or\_E3 · q = 0.95
All numbers sourced from `data/ml/T3_*/results_*.json` and `data/ml/T3_*/hypotheses.json`.
Reproduce primary run identically via `data/ml/T3_primary_check/` (see §Reproducibility below).

---

## Completed Runs

| Run | Status | Notes |
|---|---|---|
| T3\_primary | ✓ complete | E2\_or\_E3, q=0.95, table35, robustness |
| T3\_primary\_check | ✓ complete | Identical config to primary; byte-identical check passed |
| T3\_E3 | ✓ complete | E3-only label; required `folds()` dtype fix (2019 fold empty) |
| T3\_E2low | skipped | E2 AND CET1(t+12m) < 11%: 8 rows, 6 banks train+val, 0 test (below 10/5 thresholds) |
| T3\_q975 | ✓ complete | E2\_or\_E3, q=0.975 |
| SMOTE comparison | embedded | Per-fold PR-AUC in `smote_metrics` of T3\_primary; no separate run needed |

**Hypotheses mode**: all runs in full mode (2000 bootstrap replicates, h3\_budget=60); no `--quick` flag used. Runtime ≈ 37–40 s per run (LR-based H3 search is fast; identical to T2 CIs on same seed confirms full mode).

**Reproducibility (T3\_primary vs T3\_primary\_check)**: PASS — OOF (1059 predictions × 3 models) and final-test (544 predictions × 3 models) are byte-identical.

---

## Sensitivity Table

Positives report distinct positive **banks** (not observation-rows) for train+validation and test separately; a bank that appears in multiple periods counts once. Thesis minima: ≥ 10 positive banks in OOF (train+val), ≥ 5 in test. Runs below either threshold are marked **exploratory**.

| | **Primary** (E2\_or\_E3, q=0.95) | **E3** (NPL-only, q=0.95) | **E2low** | **q975** (E2\_or\_E3, q=0.975) | **SMOTE** (primary config) |
|---|---|---|---|---|---|
| OOF positives: rows / banks | 85 rows / **50 banks** | 14 rows / **12 banks** ★ | — | 39 rows / **22 banks** | = primary |
| Test positives: rows / banks | 39 rows / **21 banks** | 26 rows / **12 banks** | — | 22 rows / **11 banks** | = primary |
| Thesis minima met? | ✓ OOF 50 ≥ 10 / test 21 ≥ 5 | ⚠ OOF 12 ≥ 10 / test 12 ≥ 5 — **exploratory** | — | ✓ OOF 22 ≥ 10 / test 11 ≥ 5 | ✓ |
| Selected model | **LR** | **XGB** | — | **LR** | LR |
| OOF PR-AUC LR / RF / XGB | 0.220 / 0.162 / 0.142 | 0.029 / 0.055 / **0.049** | — | 0.110 / 0.076 / 0.073 | see §SMOTE |
| OOF ROC-AUC LR / RF / XGB | 0.681 / 0.661 / 0.653 | 0.570 / **0.732** / 0.629 | — | 0.646 / 0.613 / 0.620 | see §SMOTE |
| Final-test PR-AUC (selected) | **LR: 0.206** | **XGB: 0.103** | — | **LR: 0.211** | see §SMOTE |
| Final-test ROC-AUC (selected) | **LR: 0.595** | **XGB: —¹** | — | **LR: —¹** | see §SMOTE |
| R1 margin / test alert share | 20.0 pp / **98.2%** | 2.5 pp / 0.4% | — | 4.5 pp / 2.0% | = primary |
| H1a verdict | Not supported: RF dPR=−0.058 CI=[−0.147,+0.029]; XGB dPR=−0.078 | Not supported: RF dPR=+0.027 CI=[−0.007,+0.112]; XGB dPR=+0.020 | — | Not supported: RF dPR=−0.035 CI=[−0.155,+0.040] | — |
| H3 verdict | Not supported: dPR=−0.001 CI=[−0.106,+0.133] | Not supported: dPR=−0.011 CI=[−0.193,+0.094] | — | Not supported: dPR=+0.047 CI=[−0.018,+0.170] | — |
| H5 top-2 SHAP families | **Asset\_quality** (0.00669) > **Capital** (0.00304) | **Earnings** (0.0685) > **Capital** (0.0490) ★ | — | **Earnings** (0.0178) > **Asset\_quality** (0.00785) | — |
| `capital_earnings_rank_1_2` | 0 | **1 — exploratory** | — | 0 | — |
| H1b 10%: ML / R1 / CI | 0.282 / 0.026 / [+0.056,+0.487] | 0.231 / 0.038 / [−0.050,+0.424] | — | 0.409 / 0.045 / [+0.050,+0.765] | — |
| Capital sign (cet1\_ratio) | LR coef = **+0.331** (E2 mechanics) | XGB corr(val,SHAP) = **−0.499** (risk-reducing) ★ | — | LR coef = **+0.354** (E2 mechanics) | +0.331 |

¹ Final-test ROC-AUC for E3 XGB and q975 LR not extracted here; retrievable from `results_*.json → final_test.{model}.roc_auc`.

★ E3 is marked **exploratory** throughout: 14 OOF positives from 12 banks (just above the 10-bank minimum) and fold 3 (test\_year=2019) is empty (all 2019 rows excluded by NPL break).

---

## E3 Fold Detail

Fold 3 (test\_year=2019) contains zero rows for E3: every 2019 period (2019-06-30, 2019-12-31) has its forward 12-month window crossing the NPL series break (2020-06-30), so all are excluded by the break condition. The fold is skipped in OOF evaluation.

| Fold | Test year | Test rows | Test positives | Test pos banks |
|---|---|---|---|---|
| 1 | 2017 | 207 | 2 | 2 |
| 2 | 2018 | 211 | 5 | 4 |
| 3 | 2019 | **0** | **0** | **0** (empty — NPL break) |
| 4 | 2020 | 188 | 4 | 4 |
| 5 | 2021 | 188 | 3 | 3 |
| Final test | 2022–2024 | 499 | 26 | 12 |

The severe class imbalance (14 positives across 4 OOF folds, max 5 in one fold) explains the low OOF PR-AUC (0.029–0.055) and the exploratory status of all E3-derived conclusions.

**E3 XGB capital and NPL effect directions** (OOF SHAP, all 4 folds pooled):

| Feature | Mean SHAP | corr(feature value, SHAP) | Direction | Interpretation |
|---|---|---|---|---|
| `cet1_ratio` | −0.061 | **−0.499** | Higher capital → lower P(E3) | Capital is risk-reducing for NPL stress — sign **reverses vs primary** |
| `npl_ratio` | −0.193 | **+0.520** | Higher NPL → higher P(E3) | NPL persistence — expected |
| `roe_annualised` | −0.094 | **−0.479** | Higher ROE → lower P(E3) | Earnings buffer reduces NPL stress — expected |

The capital SHAP direction under E3 is **negative** (risk-reducing), opposite to the positive LR coefficient under E2\_or\_E3. This confirms that the positive capital sign in the primary run is an artefact of the E2 label construct (high starting CET1 → larger absolute declines), not a universal finding.

---

## SMOTE Comparison (Thesis Table 3.7)

SMOTE was evaluated on the primary configuration (E2\_or\_E3, q=0.95, same 5 folds and hyperparameters). The `smote_metrics` field stores per-fold PR-AUC per model under SMOTE oversampling; the baseline uses class-weight balancing. **`smote_metrics` does not store ROC-AUC or final-test scores**, so the comparison is fold-mean OOF PR-AUC only. Pooled OOF and final-test figures for the base (class-weight) models come from `pooled_metrics` and `final_test`.

| Model | SMOTE mean-fold OOF PR-AUC | CW mean-fold OOF PR-AUC | CW pooled OOF PR-AUC | CW pooled OOF ROC-AUC | CW final-test PR-AUC | CW final-test ROC-AUC |
|---|---|---|---|---|---|---|
| **LR** (selected) | **0.263** | 0.235 | **0.220** | **0.681** | **0.206** | **0.595** |
| RF | 0.191 | 0.222 | 0.162 | 0.661 | 0.147 | 0.596 |
| XGB | 0.175 | 0.224 | 0.142 | 0.653 | 0.156 | 0.589 |

CW = class-weight balancing (the primary approach). SMOTE pooled OOF PR-AUC/ROC-AUC and final-test SMOTE metrics are not computable from `smote_metrics` alone (per-row scores not stored).

**Conclusion**: SMOTE marginally improves LR fold-mean PR-AUC (+2.8 pp) but hurts RF (−3.1 pp) and XGB (−4.9 pp). Model selection is unchanged (LR best under both strategies). Class-weight balancing is preferred because it is consistent across all three models.

---

## Do Conclusions Change?

### H1a — Tree methods not better than LR

**Primary**: RF and XGB both worse than LR (CIs fully or nearly negative); LR selected.

**E3**: Point estimates reverse — RF dPR=+0.027, XGB dPR=+0.020 — but CIs include zero (RF CI [−0.007, +0.112]). The selected model switches to **XGB** (OOF PR-AUC 0.049 vs LR 0.029), suggesting that for the pure NPL construct, ensemble methods may extract more non-linear signal. However the difference is not statistically significant, the run is exploratory (14 OOF positives), and the absolute performance gap from the primary is large (0.049 vs 0.220 OOF PR-AUC). H1a remains *not supported*.

**q975**: Same direction as primary (RF and XGB both worse). No change.

**Conclusion**: H1a verdict is stable. The E3 point-estimate reversal warrants noting in Chapter 6 (ensemble methods may suit the NPL construct) but does not support the hypothesis and is not confirmable with 14 OOF positives.

---

### H3 — Levels + trends vs levels-only

**Primary**: dPR=−0.001, CI=[−0.106, +0.133] — trend features add nothing.

**E3**: dPR=−0.011, CI=[−0.193, +0.094] — same conclusion.

**q975**: dPR=+0.047, CI=[−0.018, +0.170] — positive point estimate but CI includes zero.

**Conclusion**: H3 verdict is stable across all variants. Trend features do not reliably improve performance at any label definition or quantile.

---

### H5 — Capital + Earnings jointly rank 1–2 in SHAP

**Primary**: Asset\_quality dominates; Capital is rank 2 but Earnings is rank 3 — H5 not supported.

**E3 (exploratory) ★**: Earnings is rank 1, Capital is rank 2 (`capital_earnings_rank_1_2 = 1`). For the pure NPL construct, the thesis-expected SHAP hierarchy is recovered. However, with only 14 OOF positives, this result is **exploratory and should not be presented as a confirmed finding**.

**q975**: Earnings rises to rank 1, but Asset\_quality is rank 2 (Capital rank 3) — H5 not supported.

**Conclusion**: H5 is not supported in the primary run. The exploratory E3 result is hypothesis-consistent but underpowered. Chapter 6 should note the label-sensitivity: the thesis-expected SHAP hierarchy emerges only under the pure NPL construct, where E2 label mechanics do not distort the capital ranking.

---

### H1b — ML better than R1 at fixed alert share

**Primary**: CI at 10% share = [+0.056, +0.487] — fully positive.

**E3**: CI = [−0.050, +0.424] — straddles zero. R1 fires on only 0.4% of test rows (R1 margin optimised to 2.5pp on E3 training data). The comparison is structurally weak: a capital headroom rule is not designed to detect NPL stress.

**q975**: CI at 10% share = [+0.050, +0.765] — fully positive; advantage larger than primary (ML=0.409 vs R1=0.045).

**Conclusion**: H1b is supported (positive CI at 10% share) for primary and q975. The E3 result is inconclusive but structurally expected — R1 is a capital rule applied to a NPL construct.

---

### Capital sign across sensitivities

| Run | Model | Capital effect | Structural explanation |
|---|---|---|---|
| Primary (E2\_or\_E3) | LR | cet1\_ratio = **+0.331** | E2 mechanics: high starting CET1 → larger absolute declines → positive label correlation |
| q975 (E2\_or\_E3) | LR | cet1\_ratio = **+0.354** | Same E2 mechanics, stable |
| E3 (NPL-only) | XGB | corr(cet1\_ratio, SHAP) = **−0.499** | Capital risk-reducing for NPL stress — sign reverses |

Chapter 6 must distinguish these two regimes. The positive capital coefficient in LR for E2\_or\_E3 is a label construct artefact, not evidence that well-capitalised banks are inherently more likely to experience distress.

---

## Robust Conclusions

The following conclusions hold across all sensitivity variants (primary, E3-exploratory, q975):

- **H1a not supported** in any variant: no evidence that RF or XGB outperforms LR at conventional significance levels. LR remains the selected model for E2\_or\_E3; XGB has a marginal, non-significant edge only on the NPL construct under E3.
- **H3 not supported** in any variant: trend features (12-month changes and ranks) add no detectable discriminative power beyond level features, regardless of quantile or label definition.
- **H2 not evaluable**: all 8 capital-breach banks either entered the OOF panel already in breach (7 banks with no pre-breach predictions) or were immediately censored at the operating point. The lead-time hypothesis cannot be assessed with this dataset structure.
- **H5 not supported in the primary run**: Asset\_quality dominates over Capital and Earnings. Under the exploratory E3 run, the thesis-expected ranking (Earnings > Capital) is recovered but is not confirmable with 14 OOF positives.
- **Post-hoc H1b positive for primary and q975**: at a 10% fixed alert share, the ML model (ranked by LR score) outperforms the R1 capital-headroom rule with a fully positive bootstrap CI. This is not supported as a pre-specified result but is a consistent post-hoc finding.

---

## Limitations

**E2 construct and positive capital coefficient**: The E2 label (absolute CET1 decline ≥ threshold) is mechanically correlated with high starting capital — a bank can only lose ≥ 2.51 pp from a high base. The positive LR coefficient for cet1\_ratio in the primary run reflects this structural correlation, not a causal risk-increasing effect of capital. Chapter 6 must clarify this to avoid a counter-intuitive reading.

**Few events (rare-event problem)**: The OOF pool has 85 E2\_or\_E3 positives across 1059 observations (8.0%) and the pure E3 label yields only 14 OOF positives. Precision-recall AUC is sensitive to small changes in the positive set at this event rate; confidence intervals are wide and the choice of quantile (q=0.95 vs q=0.975) halves the positive count. All results should be read as directional evidence, not stable point estimates.

**Early folds without signal**: Folds 1–3 (test years 2017–2019) have 0–5 non-zero LR coefficients, predicting near-constants. The pooled OOF PR-AUC is therefore dominated by folds 4–5 (2020–2021), which contain more data and more post-crisis variation. This limits the generalisability of the OOF findings to the pre-2017 period.

**R1 degeneracy under F2 optimisation**: The R1 margin chosen by F2 on training data fires on 98.2% of final-test rows (primary) — effectively a constant classifier. H1b's equal-volume comparison is therefore uninformative as a pre-specified test. The post-hoc fixed-share analysis is more meaningful but was not pre-registered.

**Possible look-ahead from restated EBA data**: The EBA transparency exercise dataset may contain restated values where later vintages correct earlier published figures. If restated values are stored as the most recent observation rather than the vintage-at-time, there is a risk of look-ahead contamination in the feature set. This cannot be assessed without vintage-level data and should be flagged as a data limitation in Chapter 6.
