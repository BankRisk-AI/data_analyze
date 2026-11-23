# Hypotheses Summary — Stage 5b-R2c

**Runs:** `data/ml/5bR_t35` (space=table35, selected=XGB) · `data/ml/5bR` (space=extended, selected=RF)  
**OOF T5 positives:** 81 (2017–2021 test folds) out of 150 total (150 includes 69 pre-OOF rows with no ML predictions).  
**Evaluable H2 events:** 9 (all primary events reached `evaluated` status; none censored).

---

## Q1 — H1b Fix

**Bugs found and fixed (hypotheses.json re-run on 2026-11-23):**

1. **Denominator wrong.** The saved value used `y.sum()=150` (all T5 positives including pre-2017 periods with no ML scores). The correct denominator is `y[mask].sum()=81` (OOF rows only).
2. **Argsort direction wrong.** Code used `argsort(−scores)[−count:]` (selects the *lowest* scoring banks at each period). The correct equal-alert-volume logic is `argsort(−scores)[:count]` (highest scoring). For pre-2017 periods all scores are NaN; NaN sorts last, so `[−count:]` always selected the same trailing rows regardless of model — explaining the identical ml_recall=0.920 across both spaces. With the corrected logic restricted to OOF periods only, the values differ.

**Corrected H1b values (denominator = 81 OOF T5 positives):**

| Space | Selected | ml numerator | ml_recall | v1_1 numerator | v1_1_recall | diff (ml−v11) |
|-------|----------|-------------|-----------|----------------|-------------|---------------|
| table35 | XGB | 81/81 | **1.000** | 75/81 | 0.9259 | +0.0741 |
| extended | RF  | 80/81 | **0.9877** | 75/81 | 0.9259 | +0.0617 |

Bootstrap 95% CI for diff (cluster by bank, 2000 replicates):
- XGB (table35): [+0.011, +0.169] — excludes 0
- RF (extended): [−0.013, +0.155] — marginally includes 0

---

## Q2 — H2 Per-Event

**Global thresholds (OOF rows):** table35 matched_far=0.0161, max_ur_0\_9=0.2897 · extended matched_far=0.0655, max_ur\_0\_9=0.4480.  
All banks have first observation 2014-12-31.  
L = t\_A − t\_B in quarters; None when t\_B=None (max\_ur\_0\_9 threshold never exceeded in the window).  
All 9 events: status=**evaluated** (no censored: first ML alert period ≠ 2014-12-31 for all events).

| Event | Bank | First obs | Mode | t_A (XGB) | t_B (XGB) | L (XGB) | t_A (RF) | t_B (RF) | L (RF) |
|-------|------|-----------|------|-----------|-----------|---------|----------|----------|--------|
| hsh_state_aid 2016-05 | 24 | 2014-12-31 | LOEO | 2 | None | None | 2 | None | None |
| popular_foltf 2017-06 | 44 | 2014-12-31 | LOEO | 4 | 4 | 0 | 4 | None | None |
| mps_recap 2017-07 | 68 | 2014-12-31 | LOEO | 3 | None | None | 3 | None | None |
| vicenza_foltf 2017-06 | 76 | 2014-12-31 | LOEO | 4 | None | None | 4 | 4 | 0 |
| veneto_foltf 2017-06 | 71 | 2014-12-31 | LOEO | 4 | None | None | 4 | None | None |
| novo_banco 2017-10 | 115 | 2015-12-31 | OOT | 2 | 2 | 0 | 2 | 2 | 0 |
| ccb_liquidation 2018-06 | 12 | 2014-12-31 | OOT | 4 | 4 | 0 | 4 | None | None |
| carige_temp_admin 2019-01 | 72 | 2014-12-31 | OOT | 3 | 3 | 0 | 3 | 3 | 0 |
| nordlb_recap 2019-12 | 19 | 2014-12-31 | OOT | 2 | None | None | 2 | None | None |

**Wilcoxon (non-zero evaluated L):** n=0 for both spaces — all evaluated L are either 0 or None.  
**L=None reason:** max_ur_0\_9 threshold not exceeded in the event window. LOEO models are trained on 1–4 semiannual periods (HSH: 1 period; Popular/Vicenza/Veneto: 3; MPS: 4), yielding a narrow training distribution; the 90th-percentile threshold is reached only when the LOEO model's score for the event bank exceeds nearly all training scores. For NordLB (OOT), the XGB/RF fold score falls between matched_far and max_ur_0\_9.  
**L=0 reason:** the last window period exceeds both thresholds simultaneously, so t\_A = t\_B.

---

## Q3 — H1a dROC-AUC

| Space | Comparison | dROC est | 95% CI | p (one-sided) |
|-------|------------|----------|--------|---------------|
| table35 | XGB vs LR | **+0.0838** | [+0.013, +0.159] | 0.010 |
| table35 | RF vs LR  | +0.0723 | [−0.005, +0.155] | 0.037 |
| extended | RF vs LR  | −0.0094 | [−0.076, +0.051] | 0.609 |
| extended | XGB vs LR | +0.0135 | [−0.060, +0.092] | 0.356 |

XGB's ROC advantage over LR is significant in the table35 space (CI excludes 0); no model is significantly better than LR in the extended space.

---

## Q4 — H5 SHAP Family Importance

**table35 (XGB):**

| Family | Primary (mean|SHAP|) | Rank | Sensitivity (merged) |
|--------|----------------------|------|----------------------|
| Asset quality | 1.3736 | 1 | 1.8546 (incl. Concentration + Growth) |
| Capital | 1.1309 | 2 | 1.1309 |
| Growth | 0.2472 | 3 | — merged into Asset quality |
| Concentration | 0.2338 | 4 | — merged into Asset quality |
| Earnings | 0.1651 | 5 | 0.1651 |
| Liquidity | 0.0 | 6 | 0.0 |

**extended (RF):**

| Family | Primary (mean|SHAP|) | Rank | Sensitivity (merged) |
|--------|----------------------|------|----------------------|
| Asset quality | 0.0912 | 1 | 0.1373 (incl. Concentration + Growth) |
| Capital | 0.0795 | 2 | 0.0795 |
| Growth | 0.0356 | 3 | — merged into Asset quality |
| Earnings | 0.0210 | 4 | 0.0210 |
| Concentration | 0.0106 | 5 | — merged into Asset quality |
| Liquidity | 0.0 | 6 | 0.0 |

Both spaces agree: Asset quality rank 1, Capital rank 2. `capital_earnings_rank_1_2 = False` (Earnings is rank 5 in both). Note: Liquidity features contribute 0 mean|SHAP| because no liquidity indicators are in the Table 3.5 / extended feature set (they map to the catch-all "Liquidity" family but have zero SHAP mass here).

---

## Q5 — Power

Based on bootstrap SE of dPR-AUC (XGB vs LR, 2000 replicates); MDD = (1.96 + 0.842) × SE.

| Space | SE(dPR) | MDD (80% power, α=0.05, two-sided) | OOF T5 pos | Evaluable events |
|-------|---------|--------------------------------------|-----------|------------------|
| table35 | 0.0711 | **0.199** | 81 | 9 |
| extended | 0.0528 | **0.148** | 81 | 9 |

The minimum detectable PR-AUC difference is 0.15–0.20. At the observed scale (|dPR|<0.014 for both comparisons in the extended space), the study is substantially underpowered for detecting the ML improvement — consistent with the non-significant p-values. The extended space search has narrower SE because RF's scores are better calibrated across the OOF set.
