"""Training orchestrator for eba_ml (§3.5, Table 3.5).

Recipe: build_dataset -> run_search -> refit_folds -> evaluate_final_test -> save_results.
Each step is a named function call; no logic lives in the orchestrator.
"""
from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.modules.eba_ml.application.dataset import build_dataset, save_dataset
from app.modules.eba_ml.application.io import get_logger, write_json
from app.modules.eba_ml.application.models import SEED, model_factory
from app.modules.eba_ml.application.training.assembly import (
    assemble_result,
    build_event_table,
    build_labels,
    build_split_report,
)
from app.modules.eba_ml.application.training.comparators import load_comparator_scores
from app.modules.eba_ml.application.training.final_test import evaluate_final_test
from app.modules.eba_ml.application.training.metrics import (
    comparator_metrics_and_predictions,
    compute_bootstrap_cis,
    compute_event_metrics,
    compute_pooled_metrics,
)
from app.modules.eba_ml.application.training.oof import refit_folds
from app.modules.eba_ml.application.training.search import run_fold_search
from app.modules.eba_ml.application.training.trainers import oob_curve
from app.modules.eba_ml.domain.constants import TARGETS

EU_EBA_V1_1_PROFILE_SHA = "28a28fa0f89da8435abdb0d6042a69cb2bff421c456926374dd202e0089f7e40"


def fit_final_model(conn, algorithm: str, target: str = "T5",
                    grid: str = "semiannual", robustness: bool = True):
    """Fit a single algorithm on all training data (<=2020) and return the fitted model.

    Used by the prediction/scoring worker (worker_handlers.py).
    """
    dataset = build_dataset(conn, grid, robustness)
    y = np.asarray([(row["bank_id"], row["period"]) in dataset["targets"][target]
                    for row in dataset["rows"]], dtype=int)
    train_idx = np.asarray([
        i for i, row in enumerate(dataset["rows"]) if row["period"].year <= 2020])
    model = model_factory()[algorithm]
    model.fit(dataset["X"][train_idx], y[train_idx])
    return model, dataset, y, train_idx


def train(conn, target: str = "T5", grid: str = "semiannual",
          out_dir: str | Path = "data/ml", robustness: bool = False,
          models: list[str] | None = None, wall_clock_hours: float = 2.0,
          space: str = "table35") -> dict[str, Any]:
    """Run the full ML training pipeline and save results JSON (§3.5).

    Steps: validate, build_dataset, search, oob_curve, refit, metrics, shap, save.
    """
    logger, started, selected_algorithms = _validate_and_seed(target, space, models)
    dataset = build_dataset(conn, grid, robustness)
    save_dataset(dataset, out_dir)
    y = build_labels(dataset, target)
    search_results, selected_params = _run_all_searches(
        dataset, y, selected_algorithms, space, started, wall_clock_hours, logger)
    final_train_idx = np.asarray([i for i, r in enumerate(dataset["rows"]) if r["period"].year <= 2020])
    rf_oob_curve = _run_oob_curve(
        dataset, y, selected_params, selected_algorithms, final_train_idx, space)
    if rf_oob_curve and space == "table35":
        selected_params["RF"]["n_estimators"] = max(
            rf_oob_curve, key=lambda v: v["oob_score"])["n_estimators"]
    predictions, fold_metrics, smote_metrics = refit_folds(
        dataset, y, selected_algorithms, selected_params, space, SEED,
        started, wall_clock_hours, logger)
    comparator_scores = load_comparator_scores(conn, dataset, EU_EBA_V1_1_PROFILE_SHA)
    final_test, ft_train_idx, test_idx = evaluate_final_test(
        dataset, y, selected_algorithms, selected_params, comparator_scores, space)
    split_report = build_split_report(dataset["rows"], y, ft_train_idx, test_idx)
    key_to_index = {f"{r['bank_id']}:{r['period'].isoformat()}": i
                    for i, r in enumerate(dataset["rows"])}
    pooled_metrics = compute_pooled_metrics(dataset, y, predictions, key_to_index)
    comp_metrics, comparator_predictions = comparator_metrics_and_predictions(
        dataset, y, comparator_scores)
    pooled_metrics.update(comp_metrics)
    event_metrics = compute_event_metrics(
        dataset, y, predictions, comparator_scores, selected_algorithms, key_to_index)
    bootstrap_cis = compute_bootstrap_cis(
        dataset, y, predictions, comparator_scores, selected_algorithms, key_to_index)
    selected_name, selected_model = _select_and_refit_champion(
        dataset, y, final_train_idx, search_results, selected_algorithms, selected_params, space)
    shap_importance = _compute_shap(
        dataset, selected_name, selected_model, final_train_idx, test_idx)
    event_table = build_event_table(conn, dataset, predictions, selected_name, comparator_scores)
    result = assemble_result(
        target, grid, space, dataset, y, selected_name, selected_algorithms,
        search_results, selected_params, split_report, fold_metrics, smote_metrics,
        pooled_metrics, final_test, shap_importance, event_metrics, bootstrap_cis,
        event_table, rf_oob_curve, predictions, comparator_predictions)
    write_json(Path(out_dir) / f"results_{target}_{grid}{'_robust' if robustness else ''}.json", result)
    logger.info("run finished")
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _validate_and_seed(
    target: str, space: str, models: list[str] | None,
) -> tuple:
    """Validate inputs, seed RNGs, return (logger, started, selected_algorithms)."""
    if target not in TARGETS:
        raise ValueError(f"unknown target: {target}")
    if space not in {"table35", "extended"}:
        raise ValueError(f"unknown search space: {space}")
    random.seed(SEED)
    np.random.seed(SEED)
    selected_algorithms = tuple(models or ("LR", "RF", "XGB"))
    invalid = set(selected_algorithms) - {"LR", "RF", "XGB"}
    if invalid:
        raise ValueError(f"unknown models: {sorted(invalid)}")
    return get_logger(), time.monotonic(), selected_algorithms


def _run_oob_curve(
    dataset: dict[str, Any], y: np.ndarray, selected_params: dict,
    selected_algorithms: tuple, final_train_idx: np.ndarray, space: str,
) -> list[dict]:
    """Run OOB curve for RF if present in selected_algorithms (§3.5)."""
    if "RF" not in selected_algorithms:
        return []
    return oob_curve(dataset, y, selected_params["RF"], final_train_idx, space)


def _run_all_searches(
    dataset: dict[str, Any], y: np.ndarray, algorithms: tuple,
    space: str, started: float, wall_clock_hours: float, logger,
) -> tuple[dict, dict]:
    """Run fold search for each algorithm; return (search_results, selected_params)."""
    search_results: dict[str, list] = {}
    selected_params: dict[str, dict] = {}
    for name in algorithms:
        config_scores = run_fold_search(
            dataset, y, name, space, started, wall_clock_hours, logger)
        search_results[name] = config_scores
        selected_params[name] = max(
            config_scores, key=lambda v: v["mean_pr_auc"])["parameters"]
    return search_results, selected_params


def _select_and_refit_champion(
    dataset: dict[str, Any], y: np.ndarray, final_train_idx: np.ndarray,
    search_results: dict, algorithm_names: tuple,
    selected_params: dict, space: str,
) -> tuple[str, Any]:
    """Select the best algorithm by mean OOF PR-AUC and refit on full training data (§3.5)."""
    selected_name = max(
        algorithm_names,
        key=lambda name: max(
            search_results[name], key=lambda v: v["mean_pr_auc"])["mean_pr_auc"])
    positives = int(y[final_train_idx].sum())
    weight = (len(final_train_idx) - positives) / positives if positives else 1.0
    selected_model = model_factory(
        selected_name, selected_params[selected_name], weight, space=space)
    selected_model.fit(dataset["X"][final_train_idx], y[final_train_idx])
    return selected_name, selected_model


def _compute_shap(
    dataset: dict[str, Any], selected_name: str, selected_model,
    final_train_idx: np.ndarray, test_idx: np.ndarray,
) -> dict[str, float]:
    """Compute mean-absolute SHAP importances for the champion model (H5)."""
    import shap
    shap_idx = test_idx if len(test_idx) else final_train_idx
    if selected_name == "LR":
        imputer = selected_model.named_steps["imputer"]
        scaler = selected_model.named_steps["scale"]
        train_values = scaler.transform(imputer.transform(dataset["X"][final_train_idx]))
        explain_values = scaler.transform(imputer.transform(dataset["X"][shap_idx]))
        explanation = shap.LinearExplainer(selected_model.named_steps["model"], train_values)
        shap_columns = list(imputer.get_feature_names_out(dataset["columns"]))
    else:
        explanation = shap.TreeExplainer(selected_model)
        explain_values = dataset["X"][shap_idx]
        shap_columns = list(dataset["columns"])
    values = explanation.shap_values(explain_values)
    values = values[1] if isinstance(values, list) else values
    return {col: float(np.nanmean(np.abs(values[:, i])))
            for i, col in enumerate(shap_columns)}
