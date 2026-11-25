"""Registry import and model lifecycle persistence."""
from __future__ import annotations

import hashlib
import io
import json
import platform
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import numpy as np

from app.modules.eba_ml.infrastructure.artifacts import ArtifactStore

_SHAP_NOTE = (
    "Under label E2_or_E3 the capital ratios have a positive effect because "
    "E2 mostly captures capital drawdowns of well-capitalised banks; "
    "under E3 alone the effect is negative (thesis sensitivity T-3)."
)


def _global_oof_shap(dataset: dict, y: np.ndarray, algorithm: str, params: dict,
                     families_cfg: dict, space: str = "table35") -> dict:
    """OOF SHAP per base feature + family (matches H5 primary output).

    Uses all training rows as LinearExplainer background (deterministic, no
    random sampling). Family means reproduce compute_h5() within floating-point
    tolerance.
    """
    import shap as shap_lib
    from app.modules.eba_ml.application.dataset import folds
    from app.modules.eba_ml.application.models import model_factory

    columns = dataset["columns"]
    n_cols = len(columns)
    col_to_idx = {col: j for j, col in enumerate(columns)}
    rows = dataset["rows"]
    valid_mask = y >= 0

    shap_rows: list[np.ndarray] = []
    value_rows: list[np.ndarray] = []

    for train_idx, test_idx in folds(rows):
        train_valid = train_idx[valid_mask[train_idx]]
        test_valid = test_idx[valid_mask[test_idx]]
        if not len(train_valid) or not len(test_valid):
            continue
        pos = int(y[train_valid].sum())
        if pos == 0 or pos == len(train_valid):
            continue
        pw = (len(train_valid) - pos) / max(1, pos)
        mdl = model_factory(algorithm, params, pw, space=space)
        mdl.fit(dataset["X"][train_valid], y[train_valid])

        X_test = dataset["X"][test_valid]
        if algorithm == "LR":
            bg = mdl["scale"].transform(mdl["imputer"].transform(dataset["X"][train_valid]))
            exp = shap_lib.LinearExplainer(mdl.named_steps["model"], bg)
            sv = exp.shap_values(
                mdl["scale"].transform(mdl["imputer"].transform(X_test)))
            names_out = mdl["imputer"].get_feature_names_out(np.asarray(columns))
            sv_arr = np.asarray(sv)
            aligned = np.zeros((sv_arr.shape[0], n_cols))
            for i, name in enumerate(names_out):
                if i < sv_arr.shape[1] and name in col_to_idx:
                    aligned[:, col_to_idx[name]] = sv_arr[:, i]
            shap_rows.append(aligned)
        else:
            exp = shap_lib.TreeExplainer(mdl)
            sv_obj = exp(X_test)
            sv = sv_obj.values
            if isinstance(sv, list):
                sv = sv[-1]
            elif sv.ndim == 3:
                sv = sv[:, :, 1]
            shap_rows.append(np.asarray(sv)[:, :n_cols])

        value_rows.append(X_test[:, :n_cols])

    if not shap_rows:
        return {}

    S = np.vstack(shap_rows)
    V = np.vstack(value_rows)

    # Group columns by base feature name
    base_to_cols: dict[str, list[int]] = {}
    for j, col in enumerate(columns):
        base = col.replace("_rank", "").replace("_change12m", "").replace("_missing", "")
        base_to_cols.setdefault(base, []).append(j)

    # Per base feature: mean|SHAP| (summed across rank/change12m) and direction
    features: dict[str, dict] = {}
    for base, idxs in base_to_cols.items():
        s_sum = S[:, idxs].sum(axis=1)
        base_col = col_to_idx.get(base, idxs[0])
        v = V[:, base_col]
        mean_abs = float(np.nanmean(np.abs(s_sum)))
        finite = np.isfinite(v) & np.isfinite(s_sum)
        if finite.sum() > 2 and np.std(v[finite]) > 1e-10 and np.std(s_sum[finite]) > 1e-10:
            direction = float(np.corrcoef(v[finite], s_sum[finite])[0, 1])
        else:
            direction = 0.0
        features[base] = {"mean_abs_shap": mean_abs, "direction": direction}

    # Family means: matches H5 primary output exactly
    families: dict[str, float] = {}
    for family, fam_features in families_cfg.items():
        idxs = []
        for feat in fam_features:
            idxs.extend(base_to_cols.get(feat, []))
        if idxs:
            families[family] = float(np.nanmean(np.abs(S[:, idxs])))

    return {"features": features, "families": families}


def update_t3_shap_model_cards(
    conn,
    result_path: str | Path = "data/ml/T3_primary/results_E2_or_E3_semiannual_robust.json",
) -> None:
    """Add global SHAP, LR background artefact, and note to T3-primary model cards.

    Idempotent: safe to call twice (re-writes identical data).
    """
    import joblib
    import yaml

    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    cfg = yaml.safe_load(Path("config/ml.yaml").read_text())
    families_cfg = cfg.get("shap_families", {})

    from app.modules.eba_ml.application.dataset import build_dataset
    from app.modules.eba_ml.domain.labels import build_labels

    dataset_obj = build_dataset(conn, result["grid"], robustness=True)
    r0_levels = cfg.get("r0_levels", {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105})
    horizon = cfg.get("horizon_months", 12)
    npl_break = date.fromisoformat(cfg.get("npl_series_break", "2020-06-30"))
    y_full, included, _ = build_labels(
        dataset_obj["rows"], result["label"], 0.95, horizon, r0_levels, npl_break)
    pred_idx = np.flatnonzero(included)
    pred_rows = [dataset_obj["rows"][i] for i in pred_idx]
    X = dataset_obj["X"][pred_idx]
    y = y_full[included].astype(int)
    pred_dataset = {**dataset_obj, "rows": pred_rows, "X": X}

    train_idx = np.asarray(
        [i for i, r in enumerate(pred_rows) if r["period"].year <= 2020], dtype=int)

    store = ArtifactStore()
    with conn.cursor() as cur:
        for algorithm in ("LR", "RF", "XGB"):
            name = f"thesis-T3-primary-{algorithm.lower()}"
            cur.execute("SELECT model_id,artifact_sha256,model_card FROM ml_model WHERE name=%s", (name,))
            row = cur.fetchone()
            if not row:
                continue
            model_id, sha, card = row
            card = card or {}

            params = result["selected_parameters"][algorithm]
            global_shap = _global_oof_shap(
                pred_dataset, y, algorithm, params, families_cfg,
                space=result.get("space", "table35"))

            new_fields: dict = {
                "global_shap": global_shap,
                "shap_note": _SHAP_NOTE,
            }

            if algorithm == "LR":
                # Store background sample (all training rows transformed) in ArtifactStore
                fitted_lr = store.load_model(sha, card["format"])
                X_bg = fitted_lr[:-1].transform(X[train_idx])
                buf = io.BytesIO()
                joblib.dump(X_bg, buf)
                bg_sha = store.put(buf.getvalue(), {
                    "kind": "shap_background", "algorithm": "LR",
                    "source_model_sha": sha,
                    "n_rows": int(len(train_idx)),
                    "shape": list(X_bg.shape),
                })
                new_fields["shap_background_sha256"] = bg_sha

            cur.execute("""UPDATE ml_model
                           SET model_card = model_card || %s::jsonb
                           WHERE model_id=%s""",
                        (json.dumps(new_fields), model_id))
            cur.execute("""INSERT INTO audit_log(action,entity,entity_id,detail)
                           VALUES ('update_shap_card','ml_model',%s,%s)""",
                        (str(model_id), json.dumps({"algorithm": algorithm,
                                                     "n_oof_rows": global_shap.get("features", {}) and
                                                     len(global_shap.get("features", {}))})))


def import_thesis_experiment(conn, result_path: str | Path = "data/ml/results_T5_semiannual_robust.json") -> int:
    """Import the protected 5c run idempotently; return the experiment id."""
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    config = {"target": result["target"], "grid": result["grid"], "robustness": True,
              "seed": result["seed"], "budget": result["search_configurations"]}
    content = json.dumps(config, sort_keys=True).encode()
    content_hash = hashlib.sha256(content).hexdigest()
    store = ArtifactStore()
    with conn.cursor() as cur:
        cur.execute("SELECT dataset_id FROM ml_dataset WHERE content_hash=%s", (content_hash,))
        dataset = cur.fetchone()
        if dataset:
            dataset_id = dataset[0]
        else:
            cur.execute("""INSERT INTO ml_dataset
                (target,grid,feature_set,panel_hash,content_hash,manifest,row_count,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'ready') RETURNING dataset_id""",
                        (result["target"], result["grid"], "robustness_v1",
                         result["panel_hash"], content_hash,
                         json.dumps({"columns": result["columns"], "protected": True}),
                         sum(1 for _ in result["predictions"]["XGB"])))
            dataset_id = cur.fetchone()[0]
        cur.execute("SELECT experiment_id FROM ml_experiment WHERE dataset_id=%s", (dataset_id,))
        experiment = cur.fetchone()
        if experiment:
            cur.execute("UPDATE ml_dataset SET protected=true WHERE dataset_id=%s", (dataset_id,))
            cur.execute("UPDATE ml_experiment SET protected=true WHERE experiment_id=%s", (experiment[0],))
            return experiment[0]
        cur.execute("""INSERT INTO ml_experiment
            (dataset_id,config,seed,folds,budget,status,progress,metrics,artifact_refs)
            VALUES (%s,%s,%s,%s,%s,'completed',100,%s,%s) RETURNING experiment_id""",
                    (dataset_id, json.dumps(config), result["seed"],
                     json.dumps([2017, 2018, 2019, 2020, 2021]),
                     result["search_configurations"],
                     json.dumps({"pooled": result["pooled_metrics"],
                                 "final": result["final_test"]}),
                     json.dumps({"result": str(result_path)})))
        experiment_id = cur.fetchone()[0]
        cur.execute("UPDATE ml_dataset SET protected=true WHERE dataset_id=%s", (dataset_id,))
        cur.execute("UPDATE ml_experiment SET protected=true WHERE experiment_id=%s", (experiment_id,))
        for algorithm in ("LR", "RF", "XGB"):
            payload = json.dumps({"algorithm": algorithm, "result": result},
                                 sort_keys=True).encode()
            sha = store.put(payload, {"data_hash": result["panel_hash"], "config": config,
                                      "metrics": result["pooled_metrics"], "git_commit": "imported",
                                      "python": platform.python_version()})
            name = f"stage5c-robustness-{algorithm.lower()}"
            cur.execute("""INSERT INTO ml_model
                (experiment_id,name,target,grid,algorithm,hyperparameters,artifact_sha256,
                 model_card,status,protected)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'validated',true)
                ON CONFLICT (name) DO NOTHING""",
                        (experiment_id, name, result["target"], result["grid"], algorithm,
                         json.dumps({}), sha, json.dumps({"protected": True})))
        cur.execute("""INSERT INTO audit_log (action,entity,entity_id,detail)
                       VALUES ('create','ml_experiment',%s,%s)""",
                    (str(experiment_id), json.dumps({"protected": True})))
    return experiment_id


def import_t3_primary_experiment(
    conn,
    result_path: str | Path = "data/ml/T3_primary/results_E2_or_E3_semiannual_robust.json",
) -> int:
    """Refit T3_primary models, verify predictions, store artefacts, register in DB.

    Idempotent: returns existing experiment_id if already imported.
    Raises RuntimeError if final-test predictions differ from saved JSON.
    """
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    label = result["label"]
    grid = result["grid"]
    tail_quantile = 0.95
    config = {
        "label": label, "grid": grid, "feature_set": "robustness_v1",
        "tail_quantile": tail_quantile, "space": result.get("space", "table35"),
        "seed": result["seed"],
    }
    content = json.dumps(config, sort_keys=True).encode()
    content_hash = hashlib.sha256(content).hexdigest()

    store = ArtifactStore()
    with conn.cursor() as cur:
        # Idempotency check
        cur.execute("SELECT dataset_id FROM ml_dataset WHERE content_hash=%s", (content_hash,))
        dataset = cur.fetchone()
        if dataset:
            cur.execute("SELECT experiment_id FROM ml_experiment WHERE dataset_id=%s", (dataset[0],))
            experiment = cur.fetchone()
            if experiment:
                return experiment[0]
            dataset_id = dataset[0]
        else:
            cur.execute("""INSERT INTO ml_dataset
                (target,grid,feature_set,panel_hash,content_hash,manifest,row_count,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'ready') RETURNING dataset_id""",
                        (label, grid, "robustness_v1", result["panel_hash"], content_hash,
                         json.dumps({"columns": result["columns"], "protected": True}),
                         len(result.get("test_predictions", {}).get("LR", {}))))
            dataset_id = cur.fetchone()[0]
            cur.execute("UPDATE ml_dataset SET protected=true WHERE dataset_id=%s", (dataset_id,))

        # Build dataset and labels for refit
        from app.modules.eba_ml.application.dataset import build_dataset
        from app.modules.eba_ml.domain.labels import build_labels
        import yaml
        cfg = yaml.safe_load(Path("config/ml.yaml").read_text())
        dataset_obj = build_dataset(conn, grid, robustness=True)
        r0_levels = cfg.get("r0_levels", {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105})
        horizon_months = cfg.get("horizon_months", 12)
        npl_break = date.fromisoformat(cfg.get("npl_series_break", "2020-06-30"))
        y_full, included, _ = build_labels(
            dataset_obj["rows"], label, tail_quantile, horizon_months, r0_levels, npl_break)
        pred_idx = np.flatnonzero(included)
        pred_rows = [dataset_obj["rows"][i] for i in pred_idx]
        X = dataset_obj["X"][pred_idx]
        y = y_full[included].astype(int)

        train_idx = np.asarray(
            [i for i, r in enumerate(pred_rows) if r["period"].year <= 2020], dtype=int)
        test_idx = np.asarray(
            [i for i, r in enumerate(pred_rows) if 2022 <= r["period"].year <= 2024], dtype=int)

        # Get current git commit
        try:
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            git_commit = "unknown"

        from app.modules.eba_ml.application.models import SEED, model_factory
        import joblib

        selected_params = result["selected_parameters"]
        pos_weight = (len(train_idx) - int(y[train_idx].sum())) / max(1, int(y[train_idx].sum()))

        experiment_id = None
        cur.execute("""INSERT INTO ml_experiment
            (dataset_id,config,seed,folds,budget,status,progress,metrics,artifact_refs)
            VALUES (%s,%s,%s,%s,%s,'completed',100,%s,%s) RETURNING experiment_id""",
                    (dataset_id, json.dumps(config), result["seed"],
                     json.dumps([2017, 2018, 2019, 2020, 2021]),
                     result.get("search_configurations", 60),
                     json.dumps({"pooled": result["pooled_metrics"],
                                 "final": result["final_test"]}),
                     json.dumps({"result": str(result_path)})))
        experiment_id = cur.fetchone()[0]
        cur.execute("UPDATE ml_experiment SET protected=true WHERE experiment_id=%s", (experiment_id,))

        new_model_ids = {}
        for algorithm in ("LR", "RF", "XGB"):
            params = selected_params.get(algorithm, {})
            model = model_factory(algorithm, params, pos_weight,
                                  space=result.get("space", "table35"))
            model.fit(X[train_idx], y[train_idx])

            # Verify predictions match saved JSON
            proba = model.predict_proba(X[test_idx])[:, 1]
            saved = result["test_predictions"][algorithm]
            for i, p in zip(test_idx, proba):
                key = f"{pred_rows[i]['bank_id']}:{pred_rows[i]['period'].isoformat()}"
                expected = saved.get(key)
                if expected is None:
                    continue
                if abs(float(p) - float(expected)) > 1e-10:
                    raise RuntimeError(
                        f"Refit {algorithm} prediction mismatch for {key}: "
                        f"got {p:.12f}, saved {expected:.12f}")

            # Serialize
            if algorithm == "XGB":
                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                    fname = f.name
                model.save_model(fname)
                payload = Path(fname).read_bytes()
                Path(fname).unlink(missing_ok=True)
                fmt = "xgboost_json"
            else:
                buf = io.BytesIO()
                joblib.dump(model, buf)
                payload = buf.getvalue()
                fmt = "joblib"

            card = {
                "label": label, "tail_quantile": tail_quantile,
                "dataset_hash": result["panel_hash"],
                "operating_point": result["operating_point_threshold"],
                "operating_point_f2": result["operating_point_f2"],
                "git_commit": git_commit,
                "grid": grid, "space": result.get("space", "table35"),
                "algorithm": algorithm, "format": fmt,
                "hyperparameters": params,
                "r0_levels": r0_levels,
                "python": platform.python_version(),
            }
            sha = store.put(payload, card)

            name = f"thesis-T3-primary-{algorithm.lower()}"
            cur.execute("""INSERT INTO ml_model
                (experiment_id,name,target,grid,algorithm,hyperparameters,artifact_sha256,
                 model_card,status,protected)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'validated',true)
                ON CONFLICT (name) DO NOTHING RETURNING model_id""",
                        (experiment_id, name, label, grid, algorithm,
                         json.dumps(params), sha, json.dumps(card)))
            row = cur.fetchone()
            if row:
                new_model_ids[algorithm] = row[0]
            else:
                cur.execute("SELECT model_id FROM ml_model WHERE name=%s", (name,))
                new_model_ids[algorithm] = cur.fetchone()[0]

        # Supersede T5 champion: stage5c-robustness-xgb → validated with note
        cur.execute("""UPDATE ml_model SET status='validated',
                       model_card=COALESCE(model_card,'{}') ||
                           '{"note":"superseded by thesis-T3-primary: T5 target is not the thesis definition"}'::jsonb
                       WHERE name='stage5c-robustness-xgb' AND status='champion'""")
        cur.execute("""UPDATE ml_model
                       SET model_card=COALESCE(model_card,'{}') ||
                           '{"note":"superseded by thesis-T3-primary: T5 target is not the thesis definition"}'::jsonb
                       WHERE name IN ('stage5c-robustness-lr','stage5c-robustness-rf',
                                      'stage5c-robustness-xgb')""")

        # Promote LR to champion for (E2_or_E3, semiannual)
        lr_id = new_model_ids.get("LR")
        if lr_id:
            cur.execute("""UPDATE ml_model SET status='champion' WHERE model_id=%s""", (lr_id,))

        cur.execute("""INSERT INTO audit_log(action,entity,entity_id,detail)
                       VALUES ('create','ml_experiment',%s,%s)""",
                    (str(experiment_id), json.dumps({
                        "protected": True, "source": "T3_primary",
                        "champion": f"thesis-T3-primary-lr (model_id={new_model_ids.get('LR')})",
                    })))
    return experiment_id
