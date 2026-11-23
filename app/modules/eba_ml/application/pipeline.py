"""Deterministic Stage 5b dataset and model evaluation pipeline."""
from __future__ import annotations

import json
import logging
import random
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from app.modules.eba_ml.domain.constants import FEATURES, TARGETS
from app.modules.eba_ml.application.dataset import (
    _months, build_dataset, save_dataset, folds,
)
from app.modules.eba_ml.application.models import (
    model_factory, _search_configs, SEED, SEARCH_CONFIGURATIONS,
)
from app.modules.eba_ml.domain.metrics import (
    _classification_metrics, _cluster_bootstrap, _hyp_bootstrap, _hyp_wilcoxon,
    holm_adjust, equal_alert_volume_recall, lead_time_quarters,
)

# SHA-256 of the eu_eba v1.1 alert profile used as comparator in train() and hypotheses().
# Update this constant when the reference profile is regenerated in eba_public_analysis.
EU_EBA_V1_1_PROFILE_SHA = "28a28fa0f89da8435abdb0d6042a69cb2bff421c456926374dd202e0089f7e40"


def fit_final_model(conn, algorithm: str, target: str = "T5",
                    grid: str = "semiannual", robustness: bool = True):
    dataset = build_dataset(conn, grid, robustness)
    y = np.asarray([(row["bank_id"], row["period"]) in dataset["targets"][target]
                    for row in dataset["rows"]], dtype=int)
    train_idx = np.asarray([i for i, row in enumerate(dataset["rows"])
                            if row["period"].year <= 2020])
    model = model_factory()[algorithm]
    model.fit(dataset["X"][train_idx], y[train_idx])
    return model, dataset, y, train_idx


def train(conn, target: str = "T5", grid: str = "semiannual",
          out_dir: str | Path = "data/ml", robustness: bool = False,
          models: list[str] | None = None, wall_clock_hours: float = 2.0,
          space: str = "table35") -> dict[str, Any]:
    if target not in TARGETS:
        raise ValueError(f"unknown target: {target}")
    from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss, log_loss

    random.seed(SEED)
    np.random.seed(SEED)
    selected_algorithms = tuple(models or ("LR", "RF", "XGB"))
    invalid = set(selected_algorithms) - {"LR", "RF", "XGB"}
    if invalid:
        raise ValueError(f"unknown models: {sorted(invalid)}")
    if space not in {"table35", "extended"}:
        raise ValueError(f"unknown search space: {space}")
    started = time.monotonic()
    logger = logging.getLogger("eba.ml_redo")
    if not logger.handlers:
        Path("logs").mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler("logs/ml_redo.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    dataset = build_dataset(conn, grid, robustness)
    save_dataset(dataset, out_dir)
    y = np.asarray([(row["bank_id"], row["period"]) in dataset["targets"][target]
                    for row in dataset["rows"]], dtype=int)
    split_report = []
    for fold_number, (train_indices, test_indices) in enumerate(folds(dataset["rows"]), 1):
        test_year = 2016 + fold_number
        split_report.append({
            "fold": fold_number, "train_rows": int(len(train_indices)),
            "train_positives": int(y[train_indices].sum()),
            "test_rows": int(len(test_indices)),
            "test_positives": int(y[test_indices].sum()),
            "train_share_percent": float(100 * len(train_indices) /
                                         (len(train_indices) + len(test_indices)))
            if len(train_indices) + len(test_indices) else 0.0,
            "train_positive_rate_percent": float(100 * y[train_indices].mean())
            if len(train_indices) else 0.0,
            "test_positive_rate_percent": float(100 * y[test_indices].mean())
            if len(test_indices) else 0.0,
            "embargo_year": test_year - 1,
        })
    predictions: dict[str, dict[str, float]] = {}
    fold_metrics = []
    search_results = {}
    selected_params = {}
    smote_metrics = []
    for name in selected_algorithms:
        config_scores = []
        configs = _search_configs(name, space)
        for config_number, params in enumerate(configs):
            if time.monotonic() - started > wall_clock_hours * 3600:
                raise TimeoutError("ML search exceeded wall-clock limit")
            logger.info("configuration model=%s number=%d/%d", name,
                        config_number + 1, len(configs))
            scores = []
            for train_idx, test_idx in folds(dataset["rows"]):
                if not len(test_idx) or not len(train_idx):
                    continue
                positives = int(y[train_idx].sum())
                weight = (len(train_idx) - positives) / positives if positives else 1.0
                candidate = model_factory(name, params, weight, space=space)
                candidate.fit(dataset["X"][train_idx], y[train_idx])
                scores.append(float(average_precision_score(
                    y[test_idx], candidate.predict_proba(dataset["X"][test_idx])[:, 1])))
            config_scores.append({"configuration": config_number, "parameters": params,
                                  "fold_pr_auc": scores, "mean_pr_auc": float(np.mean(scores))})
        search_results[name] = config_scores
        selected_params[name] = max(config_scores, key=lambda value: value["mean_pr_auc"])["parameters"]
    final_train_idx = np.asarray([i for i, row in enumerate(dataset["rows"])
                                  if row["period"].year <= 2020])
    oob_curve = []
    if "RF" in selected_algorithms:
        for estimator_count in (50, 100, 150):
            oob_model = model_factory("RF", {**selected_params["RF"],
                                             "n_estimators": estimator_count},
                                      space=space)
            oob_model.fit(dataset["X"][final_train_idx], y[final_train_idx])
            oob_probability = oob_model.oob_decision_function_[:, 1]
            oob_curve.append({"n_estimators": estimator_count,
                              "oob_score": float(oob_model.oob_score_),
                              "oob_brier": float(brier_score_loss(
                                  y[final_train_idx], oob_probability)),
                              "oob_log_loss": float(log_loss(
                                  y[final_train_idx], oob_probability,
                                  labels=(0, 1)))})
        if space == "table35":
            selected_params["RF"] = {
                **selected_params["RF"],
                "n_estimators": max(oob_curve, key=lambda value: value["oob_score"])["n_estimators"],
            }
    models = {name: model_factory(name, selected_params[name], space=space)
              for name in selected_algorithms}
    logger.info("phase=refit")
    for fold_number, (train_idx, test_idx) in enumerate(folds(dataset["rows"]), 1):
        if not len(test_idx) or not len(train_idx):
            continue
        for name in models:
            if time.monotonic() - started > wall_clock_hours * 3600:
                raise TimeoutError("ML search exceeded wall-clock limit")
            positives = int(y[train_idx].sum())
            weight = (len(train_idx) - positives) / positives if positives else 1.0
            model = model_factory(name, selected_params[name], weight, space=space)
            model.fit(dataset["X"][train_idx], y[train_idx])
            probability = model.predict_proba(dataset["X"][test_idx])[:, 1]
            fold_metrics.append({"fold": fold_number, "model": name,
                                 "pr_auc": average_precision_score(y[test_idx], probability),
                                 "roc_auc": roc_auc_score(y[test_idx], probability) if len(set(y[test_idx])) > 1 else None,
                                 "brier": brier_score_loss(y[test_idx], probability)})
            predictions.setdefault(name, {}).update({
                f"{dataset['rows'][i]['bank_id']}:{dataset['rows'][i]['period'].isoformat()}": float(p)
                for i, p in zip(test_idx, probability)})
            if len(np.unique(y[train_idx])) > 1:
                from imblearn.over_sampling import SMOTE
                from sklearn.base import clone
                from sklearn.impute import SimpleImputer
                transformed = SimpleImputer(strategy="median").fit_transform(dataset["X"][train_idx])
                x_over, y_over = SMOTE(random_state=SEED).fit_resample(transformed, y[train_idx])
                comparison = clone(model)
                comparison.fit(x_over, y_over)
                test_values = SimpleImputer(strategy="median").fit(dataset["X"][train_idx]).transform(
                    dataset["X"][test_idx])
                probability = comparison.predict_proba(test_values)[:, 1]
                smote_metrics.append({"fold": fold_number, "model": name,
                                      "pr_auc": average_precision_score(y[test_idx], probability)})
    logger.info("phase=metrics")
    pooled_metrics = {}
    for name, values in predictions.items():
        keys = list(values)
        actual = np.asarray([y[next(i for i, row in enumerate(dataset["rows"])
                                     if f"{row['bank_id']}:{row['period'].isoformat()}" == key)]
                            for key in keys])
        probability = np.asarray([values[key] for key in keys])
        pooled_metrics[name] = {
            "pr_auc": float(average_precision_score(actual, probability)),
            "roc_auc": float(roc_auc_score(actual, probability)) if len(set(actual)) > 1 else None,
            "brier": float(brier_score_loss(actual, probability)),
        }
    comparator_scores = {"v1.1 score": {}, "B4": {}, "B2": {}}
    with conn.cursor() as cur:
        cur.execute("""SELECT a.bank_id,v.period_end,a.level,a.rule_results
                       FROM alert a JOIN dataset_version v USING(version_id)
                       WHERE a.profile_sha256=%s""",
                    (EU_EBA_V1_1_PROFILE_SHA,))
        alert_rows = {(bank, period): (level, payload) for bank, period, level, payload in cur.fetchall()}
    for row in dataset["rows"]:
        key = (row["bank_id"], row["period"])
        level, payload = alert_rows.get(key, ("not_evaluated", {}))
        family_scores = (payload or {}).get("family_scores", {})
        comparator_scores["v1.1 score"][key] = sum(
            float(value.get("score", 0)) for value in family_scores.values())
        npl, cet1 = row["npl_ratio"], row["cet1_ratio"]
        comparator_scores["B4"][key] = float(
            (npl is not None and npl > .08) or (cet1 is not None and cet1 < .11))
        comparator_scores["B2"][key] = float(cet1 is not None and cet1 < .11)
    for name, scores in comparator_scores.items():
        actual = np.asarray([y[i] for i, row in enumerate(dataset["rows"])])
        values = np.asarray([scores[(row["bank_id"], row["period"])] for row in dataset["rows"]])
        pooled_metrics[name] = {"pr_auc": float(average_precision_score(actual, values)),
                                "roc_auc": float(roc_auc_score(actual, values)),
                                "brier": None}
    comparator_predictions = {
        name: {f"{row['bank_id']}:{row['period'].isoformat()}":
               float(scores[(row["bank_id"], row["period"])])
               for row in dataset["rows"]}
        for name, scores in comparator_scores.items()
    }
    final_test = {}
    train_idx = np.asarray([i for i, row in enumerate(dataset["rows"]) if row["period"].year <= 2020])
    test_idx = np.asarray([i for i, row in enumerate(dataset["rows"]) if 2022 <= row["period"].year <= 2024])
    split_report.append({
        "fold": "final_test", "train_rows": int(len(train_idx)),
        "train_positives": int(y[train_idx].sum()), "test_rows": int(len(test_idx)),
        "test_positives": int(y[test_idx].sum()),
        "train_share_percent": float(100 * len(train_idx) / (len(train_idx) + len(test_idx)))
        if len(train_idx) + len(test_idx) else 0.0,
        "train_positive_rate_percent": float(100 * y[train_idx].mean()) if len(train_idx) else 0.0,
        "test_positive_rate_percent": float(100 * y[test_idx].mean()) if len(test_idx) else 0.0,
        "embargo_year": 2021,
    })
    selected_model = None
    final_positives = int(y[train_idx].sum())
    final_weight = (len(train_idx) - final_positives) / final_positives if final_positives else 1.0
    for name in models:
        model = model_factory(name, selected_params[name], final_weight, space=space)
        model.fit(dataset["X"][train_idx], y[train_idx])
        if len(test_idx) and len(set(y[test_idx])) > 1:
            probability = model.predict_proba(dataset["X"][test_idx])[:, 1]
            final_test[name] = {"pr_auc": float(average_precision_score(y[test_idx], probability)),
                                "roc_auc": float(roc_auc_score(y[test_idx], probability)),
                                "brier": float(brier_score_loss(y[test_idx], probability))}
    for name, scores in comparator_scores.items():
        values = np.asarray([scores[(dataset["rows"][i]["bank_id"],
                                     dataset["rows"][i]["period"])] for i in test_idx])
        final_test[name] = {"pr_auc": float(average_precision_score(y[test_idx], values)),
                            "roc_auc": float(roc_auc_score(y[test_idx], values)),
                            "brier": None}
    selected_name = max(selected_algorithms,
                        key=lambda name: max(search_results[name],
                                             key=lambda value: value["mean_pr_auc"])["mean_pr_auc"])
    selected_model = models[selected_name]
    positives = int(y[train_idx].sum())
    weight = (len(train_idx) - positives) / positives if positives else 1.0
    selected_model = model_factory(selected_name, selected_params[selected_name], weight, space=space)
    selected_model.fit(dataset["X"][train_idx], y[train_idx])
    import shap
    shap_idx = test_idx if len(test_idx) else train_idx
    if selected_name == "LR":
        imputer = selected_model.named_steps["imputer"]
        scaler = selected_model.named_steps["scale"]
        train_values = scaler.transform(imputer.transform(dataset["X"][train_idx]))
        explain_values = scaler.transform(imputer.transform(dataset["X"][shap_idx]))
        explanation = shap.LinearExplainer(selected_model.named_steps["model"], train_values)
        shap_columns = list(imputer.get_feature_names_out(dataset["columns"]))
    else:
        explanation = shap.TreeExplainer(selected_model)
        explain_values = dataset["X"][shap_idx]
        shap_columns = list(dataset["columns"])
    values = explanation.shap_values(explain_values)
    values = values[1] if isinstance(values, list) else values
    shap_importance = {column: float(np.nanmean(np.abs(values[:, i])))
                       for i, column in enumerate(shap_columns)}
    pooled_arrays = {}
    key_to_index = {f"{row['bank_id']}:{row['period'].isoformat()}": i
                   for i, row in enumerate(dataset["rows"])}
    for name, values in predictions.items():
       indices = np.asarray([key_to_index[key] for key in values])
       pooled_arrays[name] = (y[indices], np.asarray(list(values.values())),
                              np.asarray([dataset["rows"][i]["bank_id"] for i in indices]), indices)
    bootstrap_cis = {}
    for reference in ("v1.1 score", "B4"):
       ref_scores = np.asarray([comparator_scores[reference][(r["bank_id"], r["period"])]
                                for r in dataset["rows"]])
       for name in selected_algorithms:
           actual, scores, banks, indices = pooled_arrays[name]
           bootstrap_cis[f"{name}_vs_{reference}"] = _cluster_bootstrap(
               actual, scores, ref_scores[indices], banks)
    event_metrics = {
       name: _classification_metrics(y, np.asarray([
           scores[(row["bank_id"], row["period"])] for row in dataset["rows"]]))
       for name, scores in comparator_scores.items()
    }
    event_metrics.update({
       name: _classification_metrics(*pooled_arrays[name][:2])
       for name in selected_algorithms
    })
    catalogue = yaml.safe_load(Path("config/events.yaml").read_text()) or {}
    with conn.cursor() as cur:
       cur.execute("SELECT bank_id,trim(lei) FROM bank")
       bank_ids = {lei: bank_id for bank_id, lei in cur.fetchall()}
    selected_scores = predictions[selected_name]
    score_values = np.asarray(list(selected_scores.values()))
    red_share = np.mean(np.asarray([
       comparator_scores["v1.1 score"][(row["bank_id"], row["period"])] > 0
       for row in dataset["rows"]]))
    thresholds = {
       "matched_far": float(np.quantile(score_values, max(0.0, 1.0 - red_share))),
       "max_ur_0_9": float(np.quantile(score_values, .90)),
    }
    event_table = []
    for event in catalogue.get("events", []):
       if event.get("set") != "primary" or event.get("status") != "included":
           continue
       bank_id = bank_ids.get(str(event["bank_lei"]).strip())
       event_date = date.fromisoformat(str(event["event_date"]))
       values = [probability for key, probability in selected_scores.items()
                 if bank_id is not None and key.startswith(f"{bank_id}:")
                 and _months(event_date, -12) <= date.fromisoformat(key.split(":", 1)[1])
                 <= _months(event_date, -3)]
       probability = max(values) if values else None
       event_table.append({
           "event": event.get("name", event.get("bank_lei")),
           "probability": probability,
           "matched_far": probability is not None and probability >= thresholds["matched_far"],
           "max_ur_0_9": probability is not None and probability >= thresholds["max_ur_0_9"],
           "thresholds": thresholds,
       })
    result = {"target": target, "grid": grid, "seed": SEED, "space": space,
             "search_configurations": SEARCH_CONFIGURATIONS,
             "search_configuration_counts": {name: len(search_results[name])
                                              for name in selected_algorithms},
             "search": search_results, "selected_parameters": selected_params,
              "panel_hash": dataset["panel_hash"], "fold_metrics": fold_metrics,
              "split_report": split_report,
              "target_counts_before": dataset["target_counts_before"],
              "target_counts_after": dataset["target_counts_after"],
              "smote_metrics": smote_metrics,
              "pooled_metrics": pooled_metrics, "final_test": final_test,
              "selected_model": selected_name, "shap_importance": shap_importance,
              "event_metrics": event_metrics,
              "bootstrap_cis": bootstrap_cis,
              "event_table": event_table,
              "oob_curve": oob_curve,
              "predictions": predictions, "columns": dataset["columns"],
              "comparator_predictions": comparator_predictions,
              # Keep the identity/label index beside predictions so later
              # sensitivity reports do not need to reopen the database.
              "rows": [{"bank_id": row["bank_id"], "period": row["period"].isoformat(),
                        "label": int(y[i])}
                       for i, row in enumerate(dataset["rows"])]}
    suffix = "_robust" if robustness else ""
    path = Path(out_dir) / f"results_{target}_{grid}{suffix}.json"
    logger.info("phase=save")
    path.write_text(json.dumps(result, indent=2, sort_keys=True))
    logger.info("run finished")
    return result


def hypotheses(run_dir: str | Path, seed: int = SEED, quick: bool = False) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score
    logger = logging.getLogger("eba.ml_redo")
    if not logger.handlers:
        Path("logs").mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler("logs/ml_redo.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    logger.info("hypotheses run=%s phase=metrics", run_dir)
    run = Path(run_dir)
    result_path = next(run.glob("results_*.json"))
    artifact = json.loads(result_path.read_text())
    from app.core.config import get_schema
    from app.core.database import connect
    conn = connect(get_schema())
    replicates = 20 if quick else 2000
    try:
        dataset = build_dataset(conn, artifact.get("grid", "semiannual"), True)
        rows = dataset["rows"]
        keys = np.asarray([f"{r['bank_id']}:{r['period'].isoformat()}" for r in rows])
        key_index = {key: i for i, key in enumerate(keys)}
        target = artifact.get("target", "T5")
        y = np.asarray([(r["bank_id"], r["period"]) in dataset["targets"][target] for r in rows], dtype=int)
        predictions = artifact.get("predictions", {})
        arrays = {name: np.asarray([scores.get(key, np.nan) for key in keys], dtype=float)
                  for name, scores in predictions.items()}
        valid = {name: np.isfinite(values) for name, values in arrays.items()}
        search = artifact.get("search", {})
        selected = max(("LR", "RF", "XGB"),
                       key=lambda name: max(search[name], key=lambda x: x["mean_pr_auc"])["mean_pr_auc"])
        logger.info("hypotheses run=%s phase=h1a", run_dir)
        h1 = {}
        common = valid.get("LR", np.zeros(len(y), bool))
        for name in ("RF", "XGB"):
            mask = common & valid.get(name, np.zeros(len(y), bool))
            if mask.any():
                h1[f"{name}_vs_LR"] = {
                    "dPR": _hyp_bootstrap(y[mask], arrays[name][mask], arrays["LR"][mask],
                                          np.asarray([rows[i]["bank_id"] for i in np.flatnonzero(mask)]),
                                          "pr", seed, replicates),
                    "dROC": _hyp_bootstrap(y[mask], arrays[name][mask], arrays["LR"][mask],
                                           np.asarray([rows[i]["bank_id"] for i in np.flatnonzero(mask)]),
                                           "roc", seed + 1, replicates)}
        pvals = [h1[k]["dPR"]["p_one_sided"] for k in ("RF_vs_LR", "XGB_vs_LR") if k in h1]
        for key, p in zip([k for k in ("RF_vs_LR", "XGB_vs_LR") if k in h1], holm_adjust(pvals)):
            h1[key]["dPR"]["p_holm"] = p
        fold = {}
        for item in artifact.get("fold_metrics", []):
            fold.setdefault(item["fold"], {})[item["model"]] = item["pr_auc"]
        for name in ("RF", "XGB"):
            h1.setdefault(f"{name}_vs_LR", {})["fold_wilcoxon"] = _hyp_wilcoxon(
                [v[name] - v["LR"] for v in fold.values() if name in v and "LR" in v])
        logger.info("hypotheses run=%s phase=h1b", run_dir)
        with conn.cursor() as cur:
            cur.execute("""SELECT a.bank_id,v.period_end,a.rule_results
                           FROM alert a JOIN dataset_version v USING(version_id)
                           WHERE a.profile_sha256=%s""",
                        (EU_EBA_V1_1_PROFILE_SHA,))
            alert = {(b, p): payload or {} for b, p, payload in cur.fetchall()}
        rule = np.asarray([sum(float(v.get("score", 0))
                               for v in alert.get((r["bank_id"], r["period"]), {})
                               .get("family_scores", {}).values()) for r in rows])
        selected_scores = arrays[selected]
        mask = np.isfinite(selected_scores)
        period = np.asarray([r["period"].isoformat() for r in rows])
        selected_alert = np.zeros(len(y), bool)
        rule_alert = rule > 0
        for p in np.unique(period):
            idx = np.flatnonzero(period == p)
            count = int(rule_alert[idx].sum())
            if count:
                selected_alert[idx[np.argsort(-selected_scores[idx], kind="stable")[-count:]]] = True
        h1b = {"selected_model": selected, "ml_recall": float((selected_alert & (y == 1)).sum() / max(1, y.sum())),
               "v1_1_recall": float((rule_alert & (y == 1)).sum() / max(1, y.sum()))}
        logger.info("hypotheses run=%s phase=h2", run_dir)
        h2_events = []
        probs = selected_scores[mask]
        red_share = float(np.mean(rule[mask] > 0))
        thresholds = {"matched_far": float(np.quantile(probs, max(0, 1 - red_share))),
                      "max_ur_0_9": float(np.quantile(probs, .9))}
        catalogue = yaml.safe_load(Path("config/events.yaml").read_text()) or {}
        for event in catalogue.get("events", []):
            if event.get("set") != "primary" or event.get("status") != "included":
                continue
            bank = event.get("bank_id")
            edate = date.fromisoformat(event["event_date"])
            obs = [(rows[i]["period"], selected_scores[i]) for i in np.flatnonzero(mask)
                   if rows[i]["bank_id"] == bank and _months(edate, -12) <= rows[i]["period"] <= _months(edate, -3)]
            leads = []
            for threshold in thresholds.values():
                hits = [p for p, score in obs if score >= threshold]
                leads.append((edate.year * 4 + (edate.month - 1) // 3) -
                             (hits[-1].year * 4 + (hits[-1].month - 1) // 3) if hits else None)
            h2_events.append({"event": event.get("event_id"), "t_A": leads[0], "t_B": leads[1],
                              "L": leads[0] - leads[1] if None not in leads else None,
                              "censored": None in leads})
        lengths = [e["L"] for e in h2_events if e["L"] is not None]
        h2 = {"thresholds": thresholds, "events": h2_events, "wilcoxon": _hyp_wilcoxon(lengths),
              "criterion": bool(len(lengths) and np.median(lengths) >= 1)}
        logger.info("hypotheses run=%s phase=h3", run_dir)
        level_columns = [i for i, col in enumerate(dataset["columns"])
                         if "_rank" not in col and "_change12m" not in col]
        params = max(search[selected], key=lambda x: x["mean_pr_auc"])["parameters"]
        level_pred = {}
        level_fold = {}
        for fold_no, (train_idx, test_idx) in enumerate(folds(rows), 1):
            weight = (len(train_idx) - y[train_idx].sum()) / max(1, y[train_idx].sum())
            model = model_factory(selected, params, weight, space=artifact.get("space", "table35"))
            model.fit(dataset["X"][train_idx][:, level_columns], y[train_idx])
            level_pred.update({keys[i]: float(v) for i, v in
                               zip(test_idx, model.predict_proba(dataset["X"][test_idx][:, level_columns])[:, 1])})
            level_fold[fold_no] = float(average_precision_score(
                y[test_idx], model.predict_proba(dataset["X"][test_idx][:, level_columns])[:, 1]))
        lp = np.asarray([level_pred.get(key, np.nan) for key in keys])
        h3mask = np.isfinite(selected_scores) & np.isfinite(lp)
        primary_fold = {item["fold"]: item["pr_auc"] for item in artifact.get("fold_metrics", [])
                        if item.get("model") == selected}
        h3 = {"dPR": _hyp_bootstrap(y[h3mask], selected_scores[h3mask], lp[h3mask],
                                    np.asarray([rows[i]["bank_id"] for i in np.flatnonzero(h3mask)]),
                                    "pr", seed, replicates),
              "fold_wilcoxon": _hyp_wilcoxon([
                  primary_fold[f] - level_fold[f] for f in level_fold if f in primary_fold])}
        logger.info("hypotheses run=%s phase=h5", run_dir)
        h5 = {"status": "pending", "note": "TreeExplainer requires a tree model"}
        if selected in ("RF", "XGB"):
            import shap
            train_idx = np.asarray([i for i, r in enumerate(rows) if r["period"].year <= 2020])
            explain_idx = np.flatnonzero(np.isfinite(selected_scores))
            weight = (len(train_idx) - y[train_idx].sum()) / max(1, y[train_idx].sum())
            tree = model_factory(selected, params, weight, space=artifact.get("space", "table35"))
            tree.fit(dataset["X"][train_idx], y[train_idx])
            sv = shap.TreeExplainer(tree)(dataset["X"][explain_idx]).values
            if sv.ndim == 3:
                sv = sv[:, :, 1]
            families = {"Capital": {"cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio"},
                        "Asset quality": {"npl_ratio", "stage2_share"}, "Earnings": {"roe_annualised"},
                        "Concentration": {"nace_hhi", "sovereign_hhi"}, "Growth": {"loan_growth_yoy"},
                        "Liquidity": set()}
            grouped = {}
            for j, col in enumerate(dataset["columns"]):
                base = col.split("_rank")[0].split("_change12m")[0].split("_missing")[0]
                family = next((name for name, members in families.items() if base in members), "Liquidity")
                grouped.setdefault(family, np.zeros(len(explain_idx)))
                grouped[family] += sv[:, j]
            primary = {name: float(np.mean(np.abs(value))) for name, value in grouped.items()}
            merged = {"Capital": primary.get("Capital", 0), "Earnings": primary.get("Earnings", 0),
                      "Asset quality": primary.get("Asset quality", 0) +
                      primary.get("Concentration", 0) + primary.get("Growth", 0),
                      "Liquidity": primary.get("Liquidity", 0)}
            ranks = [name for name, _ in sorted(primary.items(), key=lambda x: -x[1])]
            h5 = {"status": "computed", "primary": primary, "sensitivity": merged,
                  "capital_earnings_rank_1_2": set(("Capital", "Earnings")).issubset(set(ranks[:2]))}
        report = {"run": str(run), "selected_model": selected, "H1a": h1, "H1b": h1b,
                "H2": h2, "H3": h3, "H4": {"status": "pending - Stage 7 (BNM pilot)"},
                "H5": h5}
        logger.info("hypotheses run=%s phase=save", run_dir)
        logger.info("run finished")
        return report
    finally:
        conn.close()
