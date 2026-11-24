"""H1a: ML model pairwise comparison (RF vs LR, XGB vs LR) (§3.6, Table 3.6).

Bootstrap dPR, dROC, Holm-adjusted p-values, fold-wise Wilcoxon.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.eba_ml.domain.metrics import _hyp_bootstrap, _hyp_wilcoxon, holm_adjust
from app.modules.eba_ml.application.evaluation.context import RunContext


def compute_h1a(ctx: RunContext, seed: int, replicates: int) -> dict[str, Any]:
    """Compute pairwise model comparisons (H1a, §3.6).

    For each of (RF, XGB) vs LR: clustered bootstrap dPR and dROC,
    Holm-adjusted p-values on dPR, and fold-wise Wilcoxon on dPR.
    """
    h1: dict[str, Any] = {}
    common = ctx.valid.get("LR", np.zeros(len(ctx.y), bool))
    for name in ("RF", "XGB"):
        mask = common & ctx.valid.get(name, np.zeros(len(ctx.y), bool))
        if mask.any():
            bank_ids = np.asarray(
                [ctx.rows[i]["bank_id"] for i in np.flatnonzero(mask)])
            h1[f"{name}_vs_LR"] = {
                "dPR": _hyp_bootstrap(
                    ctx.y[mask], ctx.arrays[name][mask], ctx.arrays["LR"][mask],
                    bank_ids, "pr", seed, replicates),
                "dROC": _hyp_bootstrap(
                    ctx.y[mask], ctx.arrays[name][mask], ctx.arrays["LR"][mask],
                    bank_ids, "roc", seed + 1, replicates),
            }

    pvals = [h1[k]["dPR"]["p_one_sided"]
             for k in ("RF_vs_LR", "XGB_vs_LR") if k in h1]
    for key, p in zip([k for k in ("RF_vs_LR", "XGB_vs_LR") if k in h1],
                      holm_adjust(pvals)):
        h1[key]["dPR"]["p_holm"] = p

    fold: dict[int, dict] = {}
    for item in ctx.artifact.get("fold_metrics", []):
        fold.setdefault(item["fold"], {})[item["model"]] = item["pr_auc"]
    for name in ("RF", "XGB"):
        h1.setdefault(f"{name}_vs_LR", {})["fold_wilcoxon"] = _hyp_wilcoxon(
            [v[name] - v["LR"]
             for v in fold.values() if name in v and "LR" in v])

    return h1
