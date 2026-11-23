from __future__ import annotations

import json
from typing import Any

from app.core.config import get_schema
from app.core.database import connect
from app.core.exceptions import BadRequestError, InvalidParameter, NotFoundError
from app.modules.eba_ml.application import lifecycle
from app.modules.eba_ml.domain.exceptions import ProtectedModelError
from app.modules.eba_ml.domain.constants import (ALGORITHMS, FEATURE_SETS, GRIDS,
                                                  MAX_BUDGET, TARGETS, THRESHOLDS)
from app.modules.eba_ml.infrastructure.artifacts import ArtifactStore


def _validate(payload: dict[str, Any]) -> None:
    if payload.get("target") not in TARGETS or payload.get("grid") not in GRIDS:
        raise InvalidParameter("unknown target or grid")
    if payload.get("feature_set", "robustness_v1") not in FEATURE_SETS:
        raise InvalidParameter("unknown feature set")
    if any(fold not in (2017, 2018, 2019, 2020, 2021) for fold in payload.get("folds", [2017, 2018, 2019, 2020, 2021])):
        raise InvalidParameter("unknown fold")
    algorithms = payload.get("algorithms", ["XGB"])
    if not algorithms or any(value not in ALGORITHMS for value in algorithms):
        raise InvalidParameter("unknown algorithm")
    if payload.get("budget", 60) > MAX_BUDGET:
        raise InvalidParameter(f"budget must be <= {MAX_BUDGET}")
    if any(value not in THRESHOLDS for value in payload.get("thresholds", THRESHOLDS)):
        raise InvalidParameter("unknown threshold setting")


def _audit(cur, action: str, entity: str, entity_id: int, detail: dict | None = None):
    cur.execute("INSERT INTO audit_log(action,entity,entity_id,detail) VALUES (%s,%s,%s,%s)",
                (action, entity, str(entity_id), json.dumps(detail or {})))


def options() -> dict:
    return {"targets": TARGETS, "grids": GRIDS, "feature_sets": FEATURE_SETS,
            "algorithms": ALGORITHMS, "thresholds": THRESHOLDS, "max_budget": MAX_BUDGET,
            "folds": [2017, 2018, 2019, 2020, 2021]}


def list_rows(table: str, page: int, page_size: int, where: str = "", params=()):
    if table not in {"ml_dataset", "ml_experiment", "ml_model"}:
        raise InvalidParameter("invalid resource")
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} {where}", params)
        total = cur.fetchone()[0]
        cur.execute(f"SELECT * FROM {table} {where} ORDER BY 1 DESC LIMIT %s OFFSET %s",
                    (*params, page_size, (page - 1) * page_size))
        columns = [desc[0] for desc in cur.description]
        return {"items": [dict(zip(columns, row)) for row in cur.fetchall()],
                "page": page, "page_size": page_size, "total": total}


def get_row(table: str, key: str, value: int):
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE {key}=%s", (value,))
        row = cur.fetchone()
        if not row:
            raise NotFoundError("resource not found")
        return dict(zip([d[0] for d in cur.description], row))


def create_dataset(payload: dict) -> dict:
    _validate(payload)
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO ml_dataset
            (target,grid,feature_set,panel_hash,content_hash,manifest,row_count,status)
            VALUES (%s,%s,%s,%s,%s,%s,0,'building')
            RETURNING dataset_id""",
                    (payload["target"], payload["grid"], payload.get("feature_set", "robustness_v1"),
                     "0" * 64, payload.get("content_hash", "0" * 64), json.dumps({}))
        )
        dataset_id = cur.fetchone()[0]
        _audit(cur, "create", "ml_dataset", dataset_id)
        return {"dataset_id": dataset_id, "status": "building"}


def create_experiment(payload: dict) -> dict:
    _validate(payload)
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO import_batch(status) VALUES ('uploaded') RETURNING import_id")
        import_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO ml_dataset
            (target,grid,feature_set,panel_hash,content_hash,manifest,row_count,status)
            VALUES (%s,%s,%s,%s,%s,%s,0,'building')
            ON CONFLICT (content_hash) DO UPDATE SET content_hash=EXCLUDED.content_hash
            RETURNING dataset_id""",
                    (payload["target"], payload["grid"], payload.get("feature_set", "robustness_v1"),
                     "0" * 64, payload.get("content_hash", "0" * 64), json.dumps({})))
        dataset_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO ml_experiment(dataset_id,config,seed,folds,budget,status)
                       VALUES (%s,%s,%s,%s,%s,'queued') RETURNING experiment_id""",
                    (dataset_id, json.dumps(payload), payload.get("seed", 20261121),
                     json.dumps(payload.get("folds", [2017, 2018, 2019, 2020, 2021])),
                     payload.get("budget", 60)))
        experiment_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO job(import_id,kind,status,message)
                       VALUES (%s,'build_ml_dataset','pending','queued') RETURNING job_id""",
                    (import_id,))
        job_id = cur.fetchone()[0]
        cur.execute("UPDATE ml_experiment SET artifact_refs=%s WHERE experiment_id=%s",
                    (json.dumps({"job_id": job_id}), experiment_id))
        _audit(cur, "create", "ml_experiment", experiment_id, {"job_id": job_id})
        return {"experiment_id": experiment_id, "job_id": job_id, "status": "queued"}


def cancel_experiment(experiment_id: int) -> dict:
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute("SELECT artifact_refs,status FROM ml_experiment WHERE experiment_id=%s FOR UPDATE",
                    (experiment_id,))
        row = cur.fetchone()
        if not row:
            raise NotFoundError("experiment not found")
        refs, status = row
        if status in ("completed", "failed", "cancelled"):
            raise BadRequestError("experiment is no longer cancellable")
        job_id = (refs or {}).get("job_id")
        if job_id:
            cur.execute("UPDATE job SET cancel_requested=true WHERE job_id=%s", (job_id,))
        cur.execute("UPDATE ml_experiment SET status='cancelled' WHERE experiment_id=%s", (experiment_id,))
        _audit(cur, "cancel", "ml_experiment", experiment_id)
        return {"experiment_id": experiment_id, "status": "cancelled"}


def promote_model(model_id: int) -> dict:
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute("SELECT target,grid,status,protected FROM ml_model WHERE model_id=%s FOR UPDATE",
                    (model_id,))
        model = cur.fetchone()
        if not model:
            raise NotFoundError("model not found")
        target, grid, status, protected = model
        if status not in ("validated", "archived"):
            raise BadRequestError("only validated or archived models can become champion")
        cur.execute("""UPDATE ml_model SET status=CASE WHEN protected THEN 'validated'
                       ELSE 'archived' END WHERE target=%s AND grid=%s AND status='champion'""",
                    (target, grid))
        cur.execute("UPDATE ml_model SET status='champion' WHERE model_id=%s", (model_id,))
        _audit(cur, "promote", "ml_model", model_id)
        return {"model_id": model_id, "status": "champion"}


def archive_model(model_id: int) -> dict:
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute("SELECT status,protected FROM ml_model WHERE model_id=%s FOR UPDATE", (model_id,))
        row = cur.fetchone()
        if not row:
            raise NotFoundError("model not found")
        if row[1]:
            raise ProtectedModelError("protected models cannot be archived")
        if row[0] == "champion":
            raise ProtectedModelError("champion models cannot be archived")
        cur.execute("UPDATE ml_model SET status='archived' WHERE model_id=%s", (model_id,))
        _audit(cur, "archive", "ml_model", model_id)
        return {"model_id": model_id, "status": "archived"}


def hard_delete_model(model_id: int, model_name: str) -> None:
    with connect(get_schema()) as conn:
        lifecycle.hard_delete(conn, model_id, model_name, ArtifactStore())


def list_predictions(page: int, page_size: int, champion_only: bool) -> dict:
    where = ("WHERE p.model_id IN (SELECT model_id FROM ml_model WHERE status='champion')"
             if champion_only else "")
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT p.* FROM ml_prediction p {where}"
            f" ORDER BY p.period_end DESC,p.bank_id LIMIT %s OFFSET %s",
            (page_size, (page - 1) * page_size))
        columns = [d[0] for d in cur.description]
        return {"items": [dict(zip(columns, row)) for row in cur.fetchall()],
                "page": page, "page_size": page_size}
