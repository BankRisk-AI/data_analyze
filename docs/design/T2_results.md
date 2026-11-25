# T-2 Evaluation Results: EBA ML Stage §3.6

Run: `data/ml/T2_primary/` · Selected model: **LR** · Seed: 20261121 · Date: 2026-11-25

All numbers sourced from `results_E2_or_E3_semiannual_robust.json` and `hypotheses.json`;
no hand-written values. Reproduce with `ml hypotheses data/ml/T2_primary/` (byte-identical).

---

## H1a–H5 Verdict Table

| Hypothesis | Deciding numbers | Verdict |
|---|---|---|
| **H1a** RF vs LR | dPR = −0.058, CI [−0.147, +0.029], p_holm = 1.0 | Not supported: RF not better than LR |
| **H1a** XGB vs LR | dPR = −0.078, CI [−0.166, +0.003], p_holm = 1.0 | Not supported: XGB not better than LR |
| **H1b** equal-volume | ML recall = 1.000, R1 recall = 0.872, CI [0.00, 0.33]; R1 fires on 98.2% of rows | Not supported (CI includes 0); R1 degenerate at 20pp margin |
| **H2** lead time | n_evaluated = 0 (all 8 breach banks pre-date OOF window or first observation already alerts) | Not evaluable |
| **H3** levels+trends vs levels-only | dPR = −0.001, CI [−0.106, +0.133], p = 0.47; best levels-only params C=1 l2 | Not supported: trend features add no detectable information |
| **H4** BNM pilot | Pending (Stage 7) | — |
| **H5** SHAP ranking | Asset_quality = 0.00669 > Capital = 0.00304 > Earnings = 0.00099 > Growth = 0.00064 > Concentration = 0.000 | Not supported: Capital + Earnings not jointly rank 1–2 |

---

## Model Selection & Performance

**Selected parameters** (OOF hyperparameter search, `space=table35`):

| Model | Parameters |
|---|---|
| LR | C = 0.01, penalty = l1, solver = liblinear |
| RF | max_depth = 5, max_features = sqrt, min_samples_leaf = 10, n_estimators = 150 |
| XGB | colsample_bytree = 0.8, lr = 0.01, max_depth = 3, n_estimators = 300, reg_lambda = 10, subsample = 0.7 |

**Pooled OOF metrics** (5-fold, 2017–2021, 1059 rows, 85 positives):

| Model | PR-AUC | ROC-AUC |
|---|---|---|
| LR | 0.220 | 0.681 |
| RF | 0.162 | 0.661 |
| XGB | 0.142 | 0.653 |

**Final test metrics** (2022–2024, 544 rows, 39 positives):

| Model | PR-AUC | ROC-AUC |
|---|---|---|
| LR | 0.206 | 0.595 |
| RF | 0.147 | 0.596 |
| XGB | 0.156 | 0.589 |

**Operating point**: F2-maximised on OOF, frozen before final test. Threshold = 0.4916.

---

## Positives Per Fold

| Fold | Test year | Train+ | Val+ | Val alerts at OP | TP at OP |
|---|---|---|---|---|---|
| 1 | 2017 | 19 | 18 | 218 | 18 |
| 2 | 2018 | 32 | 19 | 72 | 9 |
| 3 | 2019 | 50 | 8 | 44 | 2 |
| 4 | 2020 | 69 | 22 | 125 | 21 |
| 5 | 2021 | 77 | 18 | 100 | 16 |
| Final test | 2022–2024 | 99 | 39 | — | — |

**Operating point (OOF)**: threshold = 0.4916 fires on 559/1059 rows; recall = 66/85 (77.6%), precision = 11.8%.

**Fold 1 inflates alert count**: fold 1's LR predicts constant 0.5000 (zero non-zero coefficients); threshold 0.4916 < 0.5000 so all 218 fold-1 rows alert. Without fold 1: 341/841 alerts, recall = 48/67 (71.6%), precision = 14.1%.

---

## Per-Fold Tail Thresholds

| Fold | Train cutoff | CET1 decline thr | NPL increase thr | n_train_compliant |
|---|---|---|---|---|
| 1 | 2015 | 1.499 pp | 1.045 pp | 311 |
| 2 | 2016 | 1.782 pp | 0.740 pp | 544 |
| 3 | 2017 | 2.054 pp | 0.595 pp | 781 |
| 4 | 2018 | 2.365 pp | 0.545 pp | 1015 |
| 5 | 2019 | 2.327 pp | 0.821 pp | 1251 |
| Final (global) | 2020 | 2.510 pp | 0.744 pp | 1483 |

CET1 threshold rises as more post-crisis data is included. NPL is non-monotone due to 2020 NPL-series-break exclusions.

---

## LR Sparsity and Coefficients

L1 penalty with C = 0.01 produces near-zero models in early folds:

| Fold | Non-zero coefs | Total coefs | Mean OOF score | Note |
|---|---|---|---|---|
| 1 | 0 | 51 | 0.5000 | constant; threshold alerts all rows |
| 2 | 2 | 54 | 0.493 | near-constant |
| 3 | 1 | 55 | 0.491 | near-constant |
| 4 | 2 | 57 | 0.502 | low spread |
| 5 | 5 | 60 | 0.496 | — |
| Final | 3 | 61 | — | cet1_ratio, total_capital_ratio, npl_ratio |

Folds 1–3 predict near-constant, explaining ROC-AUC ≈ 0.50/0.44/0.51. Coef count per fold varies because `SimpleImputer(add_indicator=True)` drops all-NaN columns from its output (fold 1 drops 10 features; fold 5 drops 1).

**Final model coefficients** (3/61 non-zero):

| Feature | Coefficient |
|---|---|
| `cet1_ratio` | +0.349 |
| `npl_ratio` | +0.208 |
| `total_capital_ratio` | +0.049 |

Positive capital signs follow from the E2 construct: E2+ banks have high starting CET1 (mean 24%) and experience large absolute declines (≥ 2.51pp). The LR correctly learns that well-capitalised banks face the highest E2 risk under the absolute-threshold label.

---

## H5 SHAP Family Importance

Ranked by mean |SHAP| across 1059 OOF rows; LR model refitted per fold with `random_state=20261121`:

| Family | Mean |SHAP| | Rank |
|---|---|---|
| Asset_quality | 0.00669 | 1 |
| Capital | 0.00304 | 2 |
| Earnings | 0.00099 | 3 |
| Growth | 0.00064 | 4 |
| Concentration | 0.000 | 5 |

Indicator columns (`missingindicator_*`) dropped from family sums.

---

## R1 Degeneracy

**R1 at 20pp margin fires on 98.2% of final-test rows** (534/544). The margin was chosen by F2 maximisation on training data but is too wide for discrimination.

**H1b equal-volume**: equal-volume comparison selects 534/544 rows for ML → recall = 1.000. R1 itself recalls 34/39 positives = 87.2%. Five positives are **missed by R1** because their capital headroom exceeds the 20pp margin (headroom mean = 27.1pp, median = 28.0pp, range 22.2–30.6pp). These are banks far above the R0 floor that experienced E2 events — confirming the E2 construct.

H1b not supported: CI [0.00, 0.33] includes 0 (R1 and ML are equivalent when both select nearly all rows).

**Post-hoc fixed-share sensitivity** (R1 ranked by minimum headroom, ML by LR score):

| Alert share | k | ML recall | R1 recall | Diff | 95% CI (cluster bootstrap, n=2000) |
|---|---|---|---|---|---|
| 10% | 54 | 0.282 | 0.026 | +0.256 | [+0.056, +0.487] |
| 20% | 109 | 0.359 | 0.154 | +0.205 | [−0.077, +0.510] |

At 10% share the CI is entirely positive; at 20% it straddles zero.

---

## E2 and E3 Construct Checks

**E2 construct** (CET1 forward decline ≥ 2.51pp, 97 E2+ rows):

| Group | Mean CET1(t) | Median CET1(t) |
|---|---|---|
| E2+ | 24.2% | 22.1% |
| E2− | 16.1% | — |

90% of E2+ rows have CET1(t) ≥ 15%. Predominantly well-capitalised banks experiencing large drawdowns, not banks near the R0 floor. The label measures absolute declines, so high starting capital creates mechanical positive correlation with E2+.

**E3 construct** (NPL forward increase ≥ 0.74pp, 63 E3+ rows):

| Group | Mean NPL(t) | Median NPL(t) |
|---|---|---|
| E3+ | 9.49% | 3.72% |
| E3− | 5.63% | 2.93% |

E3+ banks have higher baseline NPL, consistent with stress propagation; high mean vs median indicates a small number of very high-NPL banks drive the average.

**E2_rel** (forward relative CET1 ≤ −12.80%): 105 rows, 61 banks (92 train+val, 13 test), mean CET1(t) = 21.3%.

---

## Leakage Episode

The critical leakage occurred at label construction before this run was trained.

| Item | Detail |
|---|---|
| **Cause** | Original E2/E3 labels used the backward change `x(t) − x(t−12m)`, which is identical to the `*_change12m` features already in the dataset. The label was trivially predictable from one of its own features. |
| **Symptoms** | RF final-test PR-AUC = 1.000, F2 = 0.856; LR OOF PR-AUC implausibly high. |
| **Detection** | Plausibility check on single-feature PR-AUC + review of label construction formula in `domain/labels.py`. |
| **Fix** | Labels rewritten to use forward change `x(t+12m) − x(t)` (§3.5); this quantity is NOT in the feature set, which uses only level, rank, and backward-change features. |
| **Guards** | (1) `_check_leakage` in `train.py` raises `ValueError` if any single-feature PR-AUC > 0.95 (cet1_ratio in this run = 0.224, well below threshold). (2) Unit tests in `test_ml_labels.py` verify forward vs backward label timing. |

---

## Bugs Fixed

| Bug | Location | Fix |
|---|---|---|
| SHAP column misalignment for LR | `h5.py` (T-2e) | `SimpleImputer` drops all-NaN columns from output entirely; positional slicing `[:, :n_base]` misaligned SHAP for dropped columns. Replaced with `get_feature_names_out()` name→index mapping per fold. |
| H5 SHAP non-determinism | `models.py` (T-2f) | `LogisticRegression` lacked `random_state`; L1 coordinate descent has tie-breaking non-determinism near sparsity boundaries. Added `random_state=SEED`. Now byte-identical across runs. |
| Result files created 600 | `io.py:write_json` | Added `os.chmod(tmp, 0o644)` before atomic rename. |

---

## Validity Notes for Chapter 6

**E2 construct**: E2+ banks are predominantly well-capitalised (mean CET1 24%, 90% with CET1 ≥ 15%). The absolute-threshold label mechanic means high capital → higher E2 risk, reflected in positive LR capital coefficients. Chapter 6 should note this structural feature of the label when interpreting capital variables.

**Sign of capital effects**: positive `cet1_ratio` coefficient in final LR is not counter-intuitive — it encodes the structural correlation between high starting CET1 and large absolute forward declines under the E2 label. This should be explained clearly to avoid confusion with a risk-reducing interpretation.

**R1 degeneracy**: the 20pp margin chosen by F2 on training data fires on 98.2% of test rows, making H1b uninformative as a pre-specified comparison. The post-hoc fixed-share analysis (§ above) is the meaningful comparison for Chapter 6.

**H2 not evaluable**: all 8 breach banks either entered the panel already breaching, or first appear after their breach date. The lead-time hypothesis requires sufficient pre-breach observations and cannot be assessed with this dataset structure. Chapter 6 should flag this as a data limitation.

**Early folds without signal**: folds 1–3 (2017–2019 test years) have 0–1 non-zero LR coefficients, predicting near-constants. Pooled OOF metrics are therefore dominated by folds 4–5. Chapter 6 should note that model signal concentrates in the later (more data-rich) folds and that pooled OOF metrics may overstate cross-sectional generalisability.
