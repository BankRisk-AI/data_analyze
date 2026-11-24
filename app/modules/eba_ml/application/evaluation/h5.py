"""H5: SHAP feature-family importance (§3.6).

Groups SHAP values by feature family (Capital, Asset quality, Earnings, etc.)
and checks whether Capital and Earnings rank first and second.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.eba_ml.application.models import model_factory
from app.modules.eba_ml.domain.families import group_shap_values, SENSITIVITY_GROUPS
from app.modules.eba_ml.application.evaluation.context import RunContext


def compute_h5(ctx: RunContext) -> dict[str, Any]:
    """Compute grouped SHAP importances for the selected tree model (H5, §3.6).

    Returns pending status for LR (TreeExplainer requires a tree model).
    Groups: Capital, Asset quality, Earnings, Concentration, Growth, Liquidity.
    Sensitivity merges: Asset quality + Concentration + Growth.
    """
    if ctx.selected not in ("RF", "XGB"):
        return {"status": "pending", "note": "TreeExplainer requires a tree model"}

    import shap

    search = ctx.artifact.get("search", {})
    params_selected = max(
        search[ctx.selected], key=lambda x: x["mean_pr_auc"])["parameters"]
    space = ctx.artifact.get("space", "table35")

    train_idx = np.asarray([
        i for i, r in enumerate(ctx.rows) if r["period"].year <= 2020])
    explain_idx = np.flatnonzero(np.isfinite(ctx.arrays[ctx.selected]))

    weight = (len(train_idx) - ctx.y[train_idx].sum()) / max(1, ctx.y[train_idx].sum())
    tree = model_factory(ctx.selected, params_selected, weight, space=space)
    tree.fit(ctx.dataset["X"][train_idx], ctx.y[train_idx])

    sv = shap.TreeExplainer(tree)(ctx.dataset["X"][explain_idx]).values
    if sv.ndim == 3:
        sv = sv[:, :, 1]

    grouped = group_shap_values(sv, ctx.dataset["columns"])
    primary = {name: float(np.mean(np.abs(values)))
               for name, values in grouped.items()}

    merged: dict[str, float] = {}
    for group_name, sub_families in SENSITIVITY_GROUPS.items():
        merged[group_name] = sum(primary.get(f, 0) for f in sub_families)

    ranks = [name for name, _ in sorted(primary.items(), key=lambda x: -x[1])]
    return {
        "status": "computed",
        "primary": primary,
        "sensitivity": merged,
        "capital_earnings_rank_1_2": set(("Capital", "Earnings")).issubset(set(ranks[:2])),
    }
