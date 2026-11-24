"""H3: levels-only model vs levels+trends (§3.6).

Trains the selected algorithm on level features only (no _rank, _change12m columns)
and compares OOF PR-AUC via bootstrap and fold-wise Wilcoxon.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.models import model_factory, _search_configs
from app.modules.eba_ml.domain.metrics import _hyp_bootstrap, _hyp_wilcoxon
from app.modules.eba_ml.application.evaluation.context import RunContext


def compute_h3(ctx: RunContext, seed: int, replicates: int, h3_budget: int) -> dict[str, Any]:
    """Compare levels-only vs levels+trends for the selected model (H3, §3.6).

    Uses same folds, seed, and budget as the main search. Columns with
    _rank or _change12m are excluded for the levels-only model.
    """
    dataset = ctx.dataset
    rows = ctx.rows
    y = ctx.y
    selected = ctx.selected

    level_columns = [i for i, col in enumerate(dataset["columns"])
                     if "_rank" not in col and "_change12m" not in col]
    X_level = dataset["X"][:, level_columns]

    h3_configs = _search_configs(selected, ctx.artifact.get("space", "table35"))[:h3_budget]
    best_level_params, best_level_mean_pr = _search_level_configs(
        X_level, y, rows, selected, h3_configs, ctx.artifact.get("space", "table35"))

    level_pred, level_fold = _refit_level_folds(
        X_level, y, rows, ctx.keys, selected, best_level_params,
        ctx.artifact.get("space", "table35"))

    lp = np.asarray([level_pred.get(key, np.nan) for key in ctx.keys])
    h3mask = np.isfinite(ctx.arrays[selected]) & np.isfinite(lp)

    primary_fold = {item["fold"]: item["pr_auc"]
                    for item in ctx.artifact.get("fold_metrics", [])
                    if item.get("model") == selected}

    return {
        "level_params": best_level_params,
        "dPR": _hyp_bootstrap(
            y[h3mask], ctx.arrays[selected][h3mask], lp[h3mask],
            np.asarray([rows[i]["bank_id"] for i in np.flatnonzero(h3mask)]),
            "pr", seed, replicates),
        "fold_wilcoxon": _hyp_wilcoxon([
            primary_fold[f] - level_fold[f]
            for f in level_fold if f in primary_fold]),
    }


def _search_level_configs(
    X_level: np.ndarray, y: np.ndarray, rows: list,
    selected: str, h3_configs: list, space: str,
) -> tuple[dict, float]:
    """Find best config for levels-only model across folds."""
    best_mean_pr = -1.0
    best_params = h3_configs[0] if h3_configs else {}
    for config_params in h3_configs:
        fold_prs = []
        for train_idx, test_idx in folds(rows):
            if not y[test_idx].any():
                continue
            w = (len(train_idx) - y[train_idx].sum()) / max(1, y[train_idx].sum())
            m = model_factory(selected, config_params, w, space=space)
            m.fit(X_level[train_idx], y[train_idx])
            fold_prs.append(average_precision_score(
                y[test_idx], m.predict_proba(X_level[test_idx])[:, 1]))
        if fold_prs and np.mean(fold_prs) > best_mean_pr:
            best_mean_pr = float(np.mean(fold_prs))
            best_params = config_params
    return best_params, best_mean_pr


def _refit_level_folds(
    X_level: np.ndarray, y: np.ndarray, rows: list, keys: np.ndarray,
    selected: str, best_params: dict, space: str,
) -> tuple[dict, dict]:
    """Refit levels-only model on each fold; return predictions and fold PR-AUCs."""
    level_pred: dict[str, float] = {}
    level_fold: dict[int, float] = {}
    for fold_no, (train_idx, test_idx) in enumerate(folds(rows), 1):
        w = (len(train_idx) - y[train_idx].sum()) / max(1, y[train_idx].sum())
        m = model_factory(selected, best_params, w, space=space)
        m.fit(X_level[train_idx], y[train_idx])
        test_scores = m.predict_proba(X_level[test_idx])[:, 1]
        level_pred.update({keys[i]: float(v) for i, v in zip(test_idx, test_scores)})
        level_fold[fold_no] = float(average_precision_score(y[test_idx], test_scores))
    return level_pred, level_fold
