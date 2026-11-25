"""Training orchestrator for eba_ml (§3.5, Table 3.5).

Recipe: build_dataset -> build_labels -> run_search -> oob_curve -> refit_folds ->
        operating_point -> evaluate_final_test -> pooled_metrics -> save.
"""
from __future__ import annotations

import random
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from app.modules.eba_ml.application.dataset import build_dataset, save_dataset
from app.modules.eba_ml.application.io import get_logger, write_json
from app.modules.eba_ml.application.models import SEED
from app.modules.eba_ml.application.training.assembly import assemble_result, build_split_report
from app.modules.eba_ml.application.training.final_test import evaluate_final_test
from app.modules.eba_ml.application.training.metrics import compute_pooled_metrics
from app.modules.eba_ml.application.training.oof import refit_folds
from app.modules.eba_ml.application.training.search import run_fold_search
from app.modules.eba_ml.application.training.trainers import oob_curve
from app.modules.eba_ml.domain.labels import LABEL_OPTIONS, build_labels
from app.modules.eba_ml.domain.operating_point import freeze_operating_point
from app.modules.eba_ml.domain.rules import choose_r1_margin, r1_alert


def _load_ml_config() -> dict:
    return yaml.safe_load(Path("config/ml.yaml").read_text())


def train(
    conn,
    label: str | None = None,
    grid: str = "semiannual",
    out_dir: str | Path = "data/ml",
    robustness: bool = False,
    models: list[str] | None = None,
    wall_clock_hours: float = 2.0,
    space: str = "table35",
    reuse_search: bool = False,
    dataset: dict[str, Any] | None = None,
    tail_quantile: float | None = None,
    sensitivity: str | None = None,
) -> dict[str, Any]:
    """Run the full ML training pipeline and save results JSON (§3.5).

    label: target label name (E1, E2, E3, E2_or_E3); default from config/ml.yaml.
    reuse_search: skip search if <out_dir>/search.json exists and panel_hash matches.
    dataset: inject a pre-built dataset dict (skips build_dataset; for testing).
    """
    cfg = _load_ml_config()
    if label is None:
        label = cfg.get("label", "E2_or_E3")
    if label not in LABEL_OPTIONS:
        raise ValueError(f"unknown label: {label}")
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
    logger.info("phase=start label=%s grid=%s", label, grid)

    if dataset is None:
        dataset = build_dataset(conn, grid, robustness)
        save_dataset(dataset, out_dir)

    r0_levels = cfg.get("r0_levels", {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105})
    if tail_quantile is None:
        tail_quantile = cfg.get("tail_quantile", 0.95)
    horizon_months = cfg.get("horizon_months", 12)
    npl_break = date.fromisoformat(cfg.get("npl_series_break", "2020-06-30"))
    margins_pp = cfg.get("r1_margin_grid_pp", [float(x) / 2 for x in range(21)])

    y_full, included, label_meta = build_labels(
        dataset["rows"], label, tail_quantile, horizon_months, r0_levels, npl_break)

    if included.sum() == 0:
        raise ValueError("No rows in prediction sample after label filtering")

    pred_idx = np.flatnonzero(included)
    pred_rows = [dataset["rows"][i] for i in pred_idx]
    pred_dataset = {**dataset, "rows": pred_rows, "X": dataset["X"][pred_idx]}
    y = y_full[included].astype(int)

    logger.info("phase=search included=%d positives=%d", len(y), int(y.sum()))
    _check_leakage(pred_dataset, y, logger)

    search_results, selected_params = _run_all_searches(
        pred_dataset, y, selected_algorithms, space, started, wall_clock_hours, logger,
        out_dir=Path(out_dir), panel_hash=dataset["panel_hash"], reuse=reuse_search)

    final_train_idx = np.asarray([
        i for i, r in enumerate(pred_rows) if r["period"].year <= 2020])
    rf_oob_curve = _run_oob_curve(
        pred_dataset, y, selected_params, selected_algorithms, final_train_idx, space)
    if rf_oob_curve and space == "table35":
        # Minimum OOB log-loss criterion (§3.5)
        selected_params["RF"]["n_estimators"] = min(
            rf_oob_curve, key=lambda v: v["oob_log_loss"])["n_estimators"]

    train_rows_for_r1 = [pred_rows[i] for i in final_train_idx]
    r1_margin, r1_f2 = choose_r1_margin(
        train_rows_for_r1, y[final_train_idx], r0_levels, margins_pp)
    logger.info("phase=r1_margin margin_pp=%.1f f2=%.4f", r1_margin * 100, r1_f2)

    logger.info("phase=refit")
    predictions, fold_metrics, smote_metrics = refit_folds(
        pred_dataset, y, selected_algorithms, selected_params, space, SEED,
        started, wall_clock_hours, logger)

    key_to_index = {f"{r['bank_id']}:{r['period'].isoformat()}": i
                    for i, r in enumerate(pred_rows)}
    selected_model = max(
        selected_algorithms,
        key=lambda n: max(search_results[n], key=lambda v: v["mean_pr_auc"])["mean_pr_auc"])
    op_threshold, op_f2 = freeze_operating_point(
        predictions, y, key_to_index, selected_model)
    logger.info("phase=operating_point threshold=%.4f f2=%.4f", op_threshold, op_f2)

    final_test, test_predictions, ft_train_idx, test_idx = evaluate_final_test(
        pred_dataset, y, selected_algorithms, selected_params, space)
    split_report = build_split_report(pred_rows, y, ft_train_idx, test_idx)
    _log_r1_margin_grid(pred_rows, y, test_idx, r0_levels, margins_pp, logger)

    logger.info("phase=metrics")
    pooled_metrics = compute_pooled_metrics(pred_dataset, y, predictions, key_to_index)

    result = assemble_result(
        grid=grid, space=space, label=label, dataset=pred_dataset, y=y,
        algorithm_names=selected_algorithms, search_results=search_results,
        selected_params=selected_params, split_report=split_report,
        fold_metrics=fold_metrics, smote_metrics=smote_metrics,
        pooled_metrics=pooled_metrics, final_test=final_test,
        test_predictions=test_predictions,
        oob_curve_data=rf_oob_curve, predictions=predictions,
        label_meta=label_meta, r1_margin=r1_margin, r1_f2=r1_f2,
        operating_point_threshold=op_threshold, operating_point_f2=op_f2,
        selected_model=selected_model,
    )

    if sensitivity is not None:
        result["sensitivity"] = sensitivity

    suffix = f"_{label}_{grid}" + ("_robust" if robustness else "")
    write_json(Path(out_dir) / f"results{suffix}.json", result)
    logger.info("run finished")
    return result


def _run_all_searches(dataset, y, algorithms, space, started, wall_clock_hours, logger,
                      out_dir: Path | None = None, panel_hash: str | None = None,
                      reuse: bool = False):
    """Run searches for all algorithms; checkpoint to <out_dir>/search.json."""
    import json as _json
    search_path = out_dir / "search.json" if out_dir else None

    # Try to reuse previous search if hash matches
    if reuse and search_path and search_path.exists():
        try:
            cached = _json.loads(search_path.read_text())
            if cached.get("panel_hash") == panel_hash and cached.get("space") == space:
                logger.info("phase=search reusing cached search from %s", search_path)
                return cached["search_results"], cached["selected_params"]
        except Exception:
            pass

    search_results = {}
    selected_params = {}
    for name in algorithms:
        config_scores = run_fold_search(dataset, y, name, space, started, wall_clock_hours, logger)
        search_results[name] = config_scores
        selected_params[name] = max(config_scores, key=lambda v: v["mean_pr_auc"])["parameters"]

    # Checkpoint after search phase
    if search_path:
        checkpoint = {"panel_hash": panel_hash, "space": space,
                      "search_results": search_results, "selected_params": selected_params}
        write_json(search_path, checkpoint)
        logger.info("phase=search checkpoint saved to %s", search_path)

    return search_results, selected_params


def _run_oob_curve(dataset, y, selected_params, selected_algorithms, final_train_idx, space):
    if "RF" not in selected_algorithms:
        return []
    return oob_curve(dataset, y, selected_params["RF"], final_train_idx, space)


def _check_leakage(dataset: dict, y: np.ndarray, logger) -> None:
    """Raise ValueError if any single feature achieves PR-AUC > 0.95 against the label."""
    from sklearn.metrics import average_precision_score
    X, cols = dataset["X"], dataset["columns"]
    valid = y >= 0
    y_v = y[valid]
    if y_v.sum() == 0 or (y_v == 0).all():
        return
    for i, col in enumerate(cols):
        x = X[valid, i]
        finite = np.isfinite(x)
        if finite.sum() < 10 or y_v[finite].sum() == 0:
            continue
        for scores in (x[finite], -x[finite]):
            auc = float(average_precision_score(y_v[finite], scores))
            if auc > 0.95:
                raise ValueError(f"possible label leakage: {col} (PR-AUC={auc:.3f})")


def _log_r1_margin_grid(rows, y, test_idx, r0_levels, margins_pp, logger) -> None:
    """Log R1 alert F2/precision/recall/alert-share on test rows for each margin."""
    from sklearn.metrics import fbeta_score, precision_score, recall_score
    test_rows = [rows[i] for i in test_idx]
    y_test = y[test_idx]
    if y_test.sum() == 0:
        return
    logger.info("phase=r1_margin_grid rows=%d positives=%d", len(y_test), int(y_test.sum()))
    for mp in margins_pp:
        mf = mp / 100.0
        alerts = np.array([int(r1_alert(r, r0_levels, mf)) for r in test_rows])
        if alerts.sum() == 0:
            logger.info("  r1 margin_pp=%.1f alerts=0", mp)
            continue
        f2   = float(fbeta_score(y_test, alerts, beta=2, zero_division=0))
        prec = float(precision_score(y_test, alerts, zero_division=0))
        rec  = float(recall_score(y_test, alerts, zero_division=0))
        logger.info("  r1 margin_pp=%.1f f2=%.3f prec=%.3f rec=%.3f alert_share=%.3f",
                    mp, f2, prec, rec, float(alerts.mean()))
