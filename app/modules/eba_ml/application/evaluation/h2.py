"""H2: R0 breach lead time analysis (§3.6, Table 3.2).

For banks with an actual R0 breach: t_B = first breach period,
t_A = first alert at the frozen operating point before t_B.
L = t_B - t_A in quarters (positive = ML leads the breach).
"""
from __future__ import annotations
from typing import Any

import numpy as np

from app.modules.eba_ml.application.evaluation.context import RunContext
from app.modules.eba_ml.domain.metrics import _hyp_wilcoxon


def compute_h2(ctx: RunContext) -> dict[str, Any]:
    """H2: per-bank R0 breach lead time (§3.6).

    Banks with breach: t_B, t_A, L = t_B - t_A quarters.
    Banks without breach in sample: right-censored, reported as proportion.
    Wilcoxon only if >= 5 non-zero L values; else "exploratory".
    """
    r0_levels = {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105}
    op_threshold = ctx.operating_point_threshold
    artifact = ctx.artifact

    # Combine OOF and final test predictions
    all_preds: dict[str, float] = {}
    all_preds.update((artifact.get("predictions") or {}).get(ctx.selected, {}))
    all_preds.update((artifact.get("test_predictions") or {}).get(ctx.selected, {}))

    rows = ctx.rows
    by_bank: dict[int, list] = {}
    for row in rows:
        by_bank.setdefault(row["bank_id"], []).append(row)
    for bank_rows in by_bank.values():
        bank_rows.sort(key=lambda r: r["period"])

    results_per_bank = []
    right_censored = 0
    all_L: list[float] = []

    for bank_id, bank_rows in by_bank.items():
        breaches = [r for r in bank_rows if _is_breach(r, r0_levels)]
        if not breaches:
            right_censored += 1
            continue
        t_B = breaches[0]["period"]

        pre = [(r["period"], all_preds.get(f"{bank_id}:{r['period'].isoformat()}"))
               for r in bank_rows if r["period"] < t_B]
        pre = [(p, s) for p, s in pre if s is not None]

        if not pre:
            results_per_bank.append({
                "bank_id": bank_id, "t_B": t_B.isoformat(),
                "status": "no_pre_breach_predictions"})
            continue

        pre_sorted = sorted(pre)
        first_period, first_score = pre_sorted[0]
        if first_score >= op_threshold:
            results_per_bank.append({
                "bank_id": bank_id, "t_B": t_B.isoformat(),
                "status": "censored_first_already_alerts",
                "first_pred_period": first_period.isoformat()})
            continue

        alert_periods = [p for p, s in pre if s >= op_threshold]
        if not alert_periods:
            results_per_bank.append({
                "bank_id": bank_id, "t_B": t_B.isoformat(),
                "status": "no_alert_before_breach"})
            continue

        t_A = min(alert_periods)
        L = _quarters_diff(t_A, t_B)
        # Flag if OOF window (2017-2021) includes the breach year
        op_overlaps_breach = t_B.year <= 2021

        results_per_bank.append({
            "bank_id": bank_id,
            "t_B": t_B.isoformat(), "t_A": t_A.isoformat(),
            "L_quarters": L, "status": "evaluated",
            "op_fitted_includes_breach_period": op_overlaps_breach,
        })
        all_L.append(float(L))

    nonzero_L = [v for v in all_L if v != 0]
    n_total_banks = len(by_bank)
    return {
        "per_bank": results_per_bank,
        "n_breach_banks": len(results_per_bank),
        "n_right_censored": right_censored,
        "right_censored_proportion": right_censored / n_total_banks if n_total_banks else None,
        "n_evaluated": len(all_L),
        "median_L_quarters": float(np.median(all_L)) if all_L else None,
        "wilcoxon": _hyp_wilcoxon(nonzero_L),
        "operating_point_threshold": op_threshold,
        "note": ("Operating point fitted on OOF (2017-2021); breach periods within that "
                 "window are flagged in per_bank.op_fitted_includes_breach_period"),
    }


def _is_breach(row: dict, r0_levels: dict) -> bool:
    return (row.get("cet1_ratio") is not None and
            row.get("tier1_ratio") is not None and
            row.get("total_capital_ratio") is not None and
            (row["cet1_ratio"] < r0_levels["cet1"] or
             row["tier1_ratio"] < r0_levels["tier1"] or
             row["total_capital_ratio"] < r0_levels["total_capital"]))


def _quarters_diff(t_A, t_B) -> int:
    """Quarters from t_A to t_B (positive if t_B after t_A)."""
    return (t_B.year * 4 + (t_B.month - 1) // 3) - (t_A.year * 4 + (t_A.month - 1) // 3)
