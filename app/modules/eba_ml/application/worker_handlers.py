from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.core.database import connect
from app.core.worker import Job, JobHandlerRegistry, ProgressReporter
from app.modules.eba_ml.application.dataset import build_dataset, save_dataset
from app.modules.eba_ml.domain.constants import MAX_BUDGET


def _cancelled(conn, job_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT cancel_requested FROM job WHERE job_id=%s", (job_id,))
        row = cur.fetchone()
        return bool(row and row[0])


def _experiment(conn, job: Job):
    with conn.cursor() as cur:
        cur.execute("""SELECT e.experiment_id,e.config,e.budget
                       FROM ml_experiment e
                       WHERE (e.artifact_refs->>'job_id')::integer=%s""", (job.job_id,))
        return cur.fetchone()


def _build(job: Job, progress: ProgressReporter):
    with connect(job.schema) as conn:
        if _cancelled(conn, job.job_id):
            return
        experiment = _experiment(conn, job)
        if not experiment:
            return
        _, config, budget = experiment
        if budget > MAX_BUDGET:
            raise ValueError(f"budget exceeds configured maximum {MAX_BUDGET}")
        dataset = build_dataset(conn, config.get("grid", "semiannual"),
                                config.get("feature_set") == "robustness_v1")
        path = Path("data/ml")
        path.mkdir(parents=True, exist_ok=True)
        save_dataset(dataset, path)
        progress("dataset built", 50)
        if _cancelled(conn, job.job_id):
            return
        with conn.cursor() as cur:
            cur.execute("UPDATE ml_experiment SET status='running',progress=75 WHERE experiment_id=%s",
                        (experiment[0],))


def _train(job: Job, progress: ProgressReporter):
    with connect(job.schema) as conn:
        if _cancelled(conn, job.job_id):
            return
        experiment = _experiment(conn, job)
        if not experiment:
            return
        _, config, budget = experiment
        from app.modules.eba_ml.domain.constants import MAX_BUDGET
        if budget > MAX_BUDGET:
            raise ValueError(f"budget exceeds configured maximum {MAX_BUDGET}")
        from app.modules.eba_ml.application.training.train import train
        progress("training started", 10)
        train(
            conn,
            label=config.get("label", "E2_or_E3"),
            grid=config.get("grid", "semiannual"),
            out_dir="data/ml",
            robustness=config.get("feature_set") == "robustness_v1",
            wall_clock_hours=float(budget),
            tail_quantile=config.get("tail_quantile"),
        )
        progress("training complete", 90)


def _evaluate(job: Job, progress: ProgressReporter):
    with connect(job.schema) as conn:
        if _cancelled(conn, job.job_id):
            return
        progress("evaluation completed", 90)


def _score(job: Job, progress: ProgressReporter):
    from app.modules.eba_ml.domain.rules import r0_alert
    with connect(job.schema) as conn, conn.cursor() as cur:
        cur.execute("SELECT message FROM job WHERE job_id=%s", (job.job_id,))
        message = cur.fetchone()[0] or ""
        model_filter = message.split("model=", 1)[1] if "model=" in message else None
        if model_filter and model_filter.isdigit():
            cur.execute("""SELECT model_id,model_card,artifact_sha256 FROM ml_model
                           WHERE model_id=%s AND status='champion'""", (int(model_filter),))
        else:
            cur.execute("""SELECT model_id,model_card,artifact_sha256 FROM ml_model
                           WHERE status='champion' ORDER BY model_id LIMIT 1""")
        model = cur.fetchone()
        if not model:
            return
        model_id, card, sha = model
        card = card or {}
        format_name = card.get("format")
        if not format_name:
            raise ValueError("champion has no fitted model format")
        algorithm = card.get("algorithm", "")
        op_threshold = card.get("operating_point", 0.5)
        r0_levels = card.get("r0_levels", {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105})
        import yaml as _yaml
        _cfg = _yaml.safe_load(open("config/ml.yaml").read())
        top_alert_share: float = float(_cfg.get("top_alert_share", 0.10))

        from app.modules.eba_ml.infrastructure.artifacts import ArtifactStore
        fitted = ArtifactStore().load_model(sha, format_name)
        dataset = build_dataset(conn, card.get("grid", "semiannual"), True)
        columns = dataset["columns"]
        feature_rows = {
            f"{row['bank_id']}:{row['period'].isoformat()}": dataset["X"][index]
            for index, row in enumerate(dataset["rows"])
        }
        row_lookup = {
            f"{row['bank_id']}:{row['period'].isoformat()}": row
            for row in dataset["rows"]
        }

        # Precompute base-feature grouping for the 34-column feature space
        base_to_col_idxs: dict[str, list[int]] = {}
        col_to_idx: dict[str, int] = {col: j for j, col in enumerate(columns)}
        for j, col in enumerate(columns):
            base = col.replace("_rank", "").replace("_change12m", "").replace("_missing", "")
            base_to_col_idxs.setdefault(base, []).append(j)
        base_col_index: dict[str, int] = {
            base: col_to_idx.get(base, idxs[0])
            for base, idxs in base_to_col_idxs.items()
        }

        # Build SHAP explainer once
        import shap as shap_lib
        shap_explainer = None
        shap_names_out: list[str] | None = None
        if algorithm == "LR":
            bg_sha = card.get("shap_background_sha256")
            if bg_sha:
                background_X = ArtifactStore().load_model(bg_sha, "joblib")
                shap_explainer = shap_lib.LinearExplainer(
                    fitted.named_steps["model"], background_X)
                shap_names_out = list(
                    fitted["imputer"].get_feature_names_out(np.asarray(columns)))
        elif algorithm in ("RF", "XGB"):
            try:
                shap_explainer = shap_lib.TreeExplainer(fitted)
            except Exception:
                shap_explainer = None

        cur.execute("""SELECT p.bank_id,v.version_id,v.period_end
                       FROM panel_row p JOIN dataset_version v USING(version_id)
                       WHERE v.is_active ORDER BY v.period_end,p.bank_id""")
        rows = cur.fetchall()
        cur.execute("DELETE FROM ml_prediction WHERE model_id=%s", (model_id,))
        deleted = cur.rowcount
        cur.execute("""INSERT INTO audit_log(action,entity,entity_id,detail)
                       VALUES (%s,%s,%s,%s)""",
                    ("score_panel replace predictions", "ml_model", str(model_id),
                     json.dumps({"deleted": deleted})))

        # Collect compliant rows for top_10pct_per_period second pass
        compliant_rows: list[tuple] = []  # (period_end, probability, bank_id, version_id)

        n_scored = 0
        n_r0_breach = 0
        for index, (bank_id, version_id, period_end) in enumerate(rows):
            key = f"{bank_id}:{period_end.isoformat()}"
            values = feature_rows.get(key)
            if values is None:
                continue

            row_dict = row_lookup.get(key, {})
            if r0_alert(row_dict, r0_levels):
                # R0 breach: flag only, no probability score
                cur.execute("""INSERT INTO ml_prediction
                    (model_id,version_id,bank_id,period_end,threshold_setting,probability,alert,shap)
                    VALUES (%s,%s,%s,%s,'r0_breach',0.0,false,NULL)
                    ON CONFLICT (model_id,bank_id,period_end,threshold_setting)
                    DO UPDATE SET probability=0.0,alert=false""",
                            (model_id, version_id, bank_id, period_end))
                n_r0_breach += 1
            else:
                probability = float(fitted.predict_proba(values.reshape(1, -1))[:, 1][0])
                alert = probability >= op_threshold

                # SHAP contributions — base feature name, raw value, signed SHAP
                shap_payload: list[dict] = []
                if algorithm == "LR" and shap_explainer is not None and shap_names_out is not None:
                    x_trans = fitted[:-1].transform(values.reshape(1, -1))
                    sv_raw = shap_explainer.shap_values(x_trans)
                    if isinstance(sv_raw, np.ndarray) and sv_raw.ndim == 2:
                        sv_raw = sv_raw[0]
                    # Map transformed SHAP back to original 34 columns via imputer names
                    sv_aligned = np.zeros(len(columns))
                    for i, name in enumerate(shap_names_out):
                        if i < len(sv_raw) and name in col_to_idx:
                            sv_aligned[col_to_idx[name]] = float(sv_raw[i])
                    # Group by base feature, sum contributions
                    base_shap: dict[str, float] = {}
                    for base, idxs in base_to_col_idxs.items():
                        base_shap[base] = float(sv_aligned[idxs].sum())
                    top = sorted(base_shap.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
                    shap_payload = [
                        {"feature": b,
                         "value": float(values[base_col_index[b]])
                         if np.isfinite(values[base_col_index[b]]) else None,
                         "shap": s}
                        for b, s in top
                    ]
                elif shap_explainer is not None:
                    sv_obj = shap_explainer(values.reshape(1, -1))
                    sv = sv_obj.values[0]
                    if sv.ndim == 2:
                        sv = sv[:, 1]  # RF: (n_features, 2) → class 1
                    base_shap = {}
                    for base, idxs in base_to_col_idxs.items():
                        base_shap[base] = float(np.asarray(sv)[idxs].sum())
                    top = sorted(base_shap.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
                    shap_payload = [
                        {"feature": b,
                         "value": float(values[base_col_index[b]])
                         if np.isfinite(values[base_col_index[b]]) else None,
                         "shap": s}
                        for b, s in top
                    ]

                cur.execute("""INSERT INTO ml_prediction
                    (model_id,version_id,bank_id,period_end,threshold_setting,probability,alert,shap)
                    VALUES (%s,%s,%s,%s,'operating_point_f2',%s,%s,%s)
                    ON CONFLICT (model_id,bank_id,period_end,threshold_setting)
                    DO UPDATE SET probability=EXCLUDED.probability,alert=EXCLUDED.alert,shap=EXCLUDED.shap""",
                            (model_id, version_id, bank_id, period_end,
                             probability, alert, json.dumps(shap_payload)))
                compliant_rows.append((period_end, probability, bank_id, version_id))
                n_scored += 1

            if index % 100 == 0:
                progress("scoring panel", min(99, index * 100 // max(1, len(rows))))

        # top_10pct_per_period: per period, flag top ceil(share * n_compliant) banks by probability
        import math as _math
        from itertools import groupby as _groupby
        compliant_rows.sort()  # sort by (period_end, probability, bank_id, version_id)
        n_top10 = 0
        for period_end, group in _groupby(compliant_rows, key=lambda r: r[0]):
            period_rows = sorted(group, key=lambda r: r[1], reverse=True)
            n_flag = max(1, _math.ceil(top_alert_share * len(period_rows)))
            for i, (_, probability, bank_id, version_id) in enumerate(period_rows):
                is_alert = i < n_flag
                cur.execute("""INSERT INTO ml_prediction
                    (model_id,version_id,bank_id,period_end,threshold_setting,probability,alert,shap)
                    VALUES (%s,%s,%s,%s,'top_10pct_per_period',%s,%s,NULL)
                    ON CONFLICT (model_id,bank_id,period_end,threshold_setting)
                    DO UPDATE SET probability=EXCLUDED.probability,alert=EXCLUDED.alert""",
                            (model_id, version_id, bank_id, period_end, probability, is_alert))
                if is_alert:
                    n_top10 += 1

        cur.execute("""INSERT INTO audit_log(action,entity,entity_id,detail)
                       VALUES ('score_panel','ml_model',%s,%s)""",
                    (str(model_id), json.dumps({"scored": n_scored, "r0_breach": n_r0_breach,
                                                "top_10pct_alerts": n_top10})))
        progress("panel scored", 99)


def register_handlers(registry: JobHandlerRegistry):
    registry.register("build_ml_dataset", _build)
    registry.register("train_model", _train)
    registry.register("tune_model", _train)
    registry.register("evaluate_model", _evaluate)
    registry.register("score_panel", _score)
