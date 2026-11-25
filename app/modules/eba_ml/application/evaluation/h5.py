"""H5: out-of-fold SHAP feature-family importance (§3.6).

Each fold model explains its own test rows (OOF SHAP).
Families loaded from config/ml.yaml; unknown column -> error.
LinearExplainer used when LR is selected.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.evaluation.context import RunContext
from app.modules.eba_ml.application.models import model_factory


def compute_h5(ctx: RunContext) -> dict[str, Any]:
    """OOF SHAP grouped by family from config (H5, §3.6).

    Each fold's model is refitted on that fold's training data and explains
    its own test rows. Families from config/ml.yaml shap_families.
    Unknown column -> error. LinearExplainer for LR, TreeExplainer for RF/XGB.
    """
    import shap

    cfg = yaml.safe_load(Path("config/ml.yaml").read_text())
    families_cfg = cfg.get("shap_families", {})
    sensitivity_cfg = cfg.get("shap_sensitivity_groups", {})

    _validate_families(ctx.dataset["columns"], families_cfg)

    dataset = ctx.dataset
    rows = ctx.rows
    y = ctx.y
    valid_mask = y >= 0
    selected = ctx.selected
    space = ctx.artifact.get("space", "table35")

    search = ctx.artifact.get("search", {})
    best_params = max(
        search.get(selected, [{"mean_pr_auc": 0, "parameters": {}}]),
        key=lambda x: x["mean_pr_auc"])["parameters"]

    n_base = len(dataset["columns"])
    col_to_idx = {col: j for j, col in enumerate(dataset["columns"])}
    all_shap: list[np.ndarray] = []
    lr_nonzero_per_fold: list[int] = []

    for _, (train_idx, test_idx) in enumerate(folds(rows), 1):
        train_valid = train_idx[valid_mask[train_idx]]
        test_valid = test_idx[valid_mask[test_idx]]
        if not len(train_valid) or not len(test_valid):
            continue
        positives = int(y[train_valid].sum())
        weight = (len(train_valid) - positives) / max(1, positives)
        model = model_factory(selected, best_params, weight, space=space)
        model.fit(dataset["X"][train_valid], y[train_valid])

        X_test = dataset["X"][test_valid]
        if selected == "LR":
            # Count non-zero LR coefficients for sparsity report
            coef = model.named_steps["model"].coef_.ravel()
            lr_nonzero_per_fold.append(int(np.count_nonzero(coef)))

            bg = shap.sample(dataset["X"][train_valid], min(100, len(train_valid)))
            explainer = shap.LinearExplainer(
                model.named_steps["model"],
                model.named_steps["scale"].transform(
                    model.named_steps["imputer"].transform(bg)))
            sv = explainer.shap_values(
                model.named_steps["scale"].transform(
                    model.named_steps["imputer"].transform(X_test)))

            # Map SHAP to original feature names via get_feature_names_out.
            # Indicator columns (missingindicator_*) are dropped from family sums.
            names_out = model.named_steps["imputer"].get_feature_names_out(
                np.asarray(dataset["columns"]))
            sv_arr = np.asarray(sv)
            aligned = np.zeros((sv_arr.shape[0], n_base))
            for i, name in enumerate(names_out):
                if i < sv_arr.shape[1] and name in col_to_idx:
                    aligned[:, col_to_idx[name]] = sv_arr[:, i]
            all_shap.append(aligned)
        else:
            explainer = shap.TreeExplainer(model)
            sv_obj = explainer(X_test)
            sv = sv_obj.values
            if isinstance(sv, list):
                sv = sv[-1]
            elif sv.ndim == 3:
                sv = sv[:, :, 1]
            all_shap.append(np.asarray(sv)[:, :n_base])

    if not all_shap:
        return {"status": "no_valid_folds"}

    shap_matrix = np.vstack(all_shap)
    grouped = _group_by_config(shap_matrix, dataset["columns"], families_cfg)
    primary = {name: float(np.mean(np.abs(values))) for name, values in grouped.items()}

    merged = {
        group: sum(primary.get(f, 0) for f in sub_families)
        for group, sub_families in sensitivity_cfg.items()
    }

    ranks = [n for n, _ in sorted(primary.items(), key=lambda x: -x[1])]
    result: dict[str, Any] = {
        "status": "computed",
        "primary": primary,
        "sensitivity": merged,
        "capital_earnings_rank_1_2": set(("Capital", "Earnings")).issubset(set(ranks[:2])),
        "n_explained_rows": int(shap_matrix.shape[0]),
        "indicator_columns": "dropped from family sums (not assigned to any base feature)",
    }
    if lr_nonzero_per_fold:
        result["lr_nonzero_per_fold"] = lr_nonzero_per_fold
    return result


def _validate_families(columns: list[str], families_cfg: dict):
    """Check all base feature columns have a family; unknown -> error."""
    base_names = {col.replace("_rank", "").replace("_change12m", "").replace("_missing", "")
                  for col in columns}
    all_family_features = {f for feats in families_cfg.values() for f in feats}
    unknown = base_names - all_family_features
    if unknown:
        raise ValueError(
            f"H5: columns not in any shap_families entry: {sorted(unknown)}. "
            f"Update shap_families in config/ml.yaml.")


def _group_by_config(shap_matrix: np.ndarray, columns: list[str], families_cfg: dict) -> dict:
    """Group SHAP values by family from config."""
    family_indices: dict[str, list[int]] = {name: [] for name in families_cfg}
    for col_idx, col in enumerate(columns):
        base = col.replace("_rank", "").replace("_change12m", "").replace("_missing", "")
        for family, features in families_cfg.items():
            if base in features:
                family_indices[family].append(col_idx)
                break
    return {name: shap_matrix[:, indices]
            for name, indices in family_indices.items() if indices}
