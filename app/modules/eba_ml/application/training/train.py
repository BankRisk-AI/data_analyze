"""Training orchestrator for eba_ml (§3.5, Table 3.5).

Recipe: build_dataset -> run_search -> oob_curve -> refit_folds ->
        evaluate_final_test -> pooled_metrics -> save.
Labels (y) are passed in externally; T-2 provides E2/E3 label functions.
"""
from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.modules.eba_ml.application.dataset import build_dataset, save_dataset
from app.modules.eba_ml.application.io import get_logger, write_json
from app.modules.eba_ml.application.models import SEED
from app.modules.eba_ml.application.training.assembly import assemble_result, build_split_report
from app.modules.eba_ml.application.training.final_test import evaluate_final_test
from app.modules.eba_ml.application.training.metrics import compute_pooled_metrics
from app.modules.eba_ml.application.training.oof import refit_folds
from app.modules.eba_ml.application.training.search import run_fold_search
from app.modules.eba_ml.application.training.trainers import oob_curve


def train(conn, y: np.ndarray, grid: str = "semiannual",
          out_dir: str | Path = "data/ml", robustness: bool = False,
          models: list[str] | None = None, wall_clock_hours: float = 2.0,
          space: str = "table35") -> dict[str, Any]:
    """Run the full ML training pipeline and save results JSON (§3.5).

    y: binary label array aligned to build_dataset rows; caller provides this
       (T-2 adds E2/E3 label functions).
    Steps: build_dataset -> search -> oob_curve -> refit_folds ->
           evaluate_final_test -> pooled_metrics -> save.
    """
    if space not in {"table35", "extended"}:
        raise ValueError(f"unknown search space: {space}")
    random.seed(SEED)
    np.random.seed(SEED)
    selected_algorithms = tuple(models or ("LR", "RF", "XGB"))
    invalid = set(selected_algorithms) - {"LR", "RF", "XGB"}
    if invalid:
        raise ValueError(f"unknown models: {sorted(invalid)}")

    logger = get_logger()
    started = time.monotonic()

    dataset = build_dataset(conn, grid, robustness)
    save_dataset(dataset, out_dir)

    search_results, selected_params = _run_all_searches(
        dataset, y, selected_algorithms, space, started, wall_clock_hours, logger)

    final_train_idx = np.asarray([
        i for i, r in enumerate(dataset["rows"]) if r["period"].year <= 2020])
    rf_oob_curve = _run_oob_curve(dataset, y, selected_params, selected_algorithms,
                                   final_train_idx, space)
    if rf_oob_curve and space == "table35":
        selected_params["RF"]["n_estimators"] = max(
            rf_oob_curve, key=lambda v: v["oob_score"])["n_estimators"]

    logger.info("phase=refit")
    predictions, fold_metrics, smote_metrics = refit_folds(
        dataset, y, selected_algorithms, selected_params, space, SEED,
        started, wall_clock_hours, logger)

    final_test, ft_train_idx, test_idx = evaluate_final_test(
        dataset, y, selected_algorithms, selected_params, space)
    split_report = build_split_report(dataset["rows"], y, ft_train_idx, test_idx)

    logger.info("phase=metrics")
    key_to_index = {f"{r['bank_id']}:{r['period'].isoformat()}": i
                    for i, r in enumerate(dataset["rows"])}
    pooled_metrics = compute_pooled_metrics(dataset, y, predictions, key_to_index)

    result = assemble_result(
        grid, space, dataset, y, selected_algorithms,
        search_results, selected_params, split_report, fold_metrics, smote_metrics,
        pooled_metrics, final_test, rf_oob_curve, predictions)

    write_json(Path(out_dir) / f"results_{grid}{'_robust' if robustness else ''}.json", result)
    logger.info("run finished")
    return result


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


def _run_oob_curve(
    dataset: dict[str, Any], y: np.ndarray, selected_params: dict,
    selected_algorithms: tuple, final_train_idx: np.ndarray, space: str,
) -> list[dict]:
    """Run OOB curve for RF if present in selected_algorithms (§3.5)."""
    if "RF" not in selected_algorithms:
        return []
    return oob_curve(dataset, y, selected_params["RF"], final_train_idx, space)
