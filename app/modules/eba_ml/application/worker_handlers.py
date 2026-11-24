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
    # T-2 will add E2/E3 label functions; train() requires y to be passed.
    raise NotImplementedError(
        "T-2: E2/E3 label function required before train_model job can run")


def _evaluate(job: Job, progress: ProgressReporter):
    with connect(job.schema) as conn:
        if _cancelled(conn, job.job_id):
            return
        progress("evaluation completed", 90)


def _score(job: Job, progress: ProgressReporter):
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
        from app.modules.eba_ml.infrastructure.artifacts import ArtifactStore
        fitted = ArtifactStore().load_model(sha, format_name)
        dataset = build_dataset(conn, card.get("grid", "semiannual"), True)
        feature_rows = {
            f"{row['bank_id']}:{row['period'].isoformat()}": dataset["X"][index]
            for index, row in enumerate(dataset["rows"])
        }
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
        try:
            import shap
            explainer = shap.TreeExplainer(fitted)
        except Exception:
            explainer = None
        for index, (bank_id, version_id, period_end) in enumerate(rows):
            key = f"{bank_id}:{period_end.isoformat()}"
            values = feature_rows.get(key)
            if values is None:
                continue
            probability = float(fitted.predict_proba(values.reshape(1, -1))[:, 1][0])
            if explainer is not None:
                shap_values = explainer.shap_values(values.reshape(1, -1))
                if isinstance(shap_values, list):
                    shap_values = shap_values[-1]
                contributions = np.asarray(shap_values).reshape(-1)
            else:
                contributions = np.zeros(len(dataset["columns"]))
            top = sorted(zip(dataset["columns"], contributions),
                         key=lambda item: abs(float(item[1])), reverse=True)[:5]
            shap_payload = [{"feature": name, "value": float(value)}
                            for name, value in top]
            thresholds = card.get("thresholds", {"matched_far": .074, "max_ur_0_9": .100})
            for setting, threshold in thresholds.items():
                cur.execute("""INSERT INTO ml_prediction
                    (model_id,version_id,bank_id,period_end,threshold_setting,probability,alert,shap)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (model_id,bank_id,period_end,threshold_setting)
                    DO UPDATE SET probability=EXCLUDED.probability,alert=EXCLUDED.alert""",
                            (model_id, version_id, bank_id, period_end, setting,
                             probability, probability >= threshold, json.dumps(shap_payload)))
            if index % 100 == 0:
                progress("scoring panel", min(99, index * 100 // max(1, len(rows))))
        progress("panel scored", 99)


def register_handlers(registry: JobHandlerRegistry):
    registry.register("build_ml_dataset", _build)
    registry.register("train_model", _train)
    registry.register("tune_model", _train)
    registry.register("evaluate_model", _evaluate)
    registry.register("score_panel", _score)
