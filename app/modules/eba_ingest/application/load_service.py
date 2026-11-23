"""Entry point for the load phase: status checks, job queuing, and transaction ownership."""
from __future__ import annotations

import os

from psycopg2.errors import UniqueViolation
from psycopg2.extras import Json

from app.core.config import get_schema
from app.core.database import connect
from app.modules.eba_ingest.config import LOAD_KIND
from app.modules.eba_ingest.domain.exceptions import LoadError
from app.modules.eba_ingest.infrastructure.database import repositories as repo
from app.modules.eba_ingest.application.load_executor import _load, _metadata  # noqa: F401 (_metadata re-exported for callers)


def _check_load_status(cur, import_id: int) -> None:
    cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (import_id,))
    row = cur.fetchone()
    if not row:
        raise LoadError(f"import {import_id} does not exist")
    status = row[0]
    if status in ("validated", "approved"):
        return
    if status != "failed":
        raise LoadError(f"import {import_id} cannot be loaded: status is {status}; expected validated or approved")

    cur.execute(
        "SELECT kind, status FROM job WHERE import_id=%s ORDER BY job_id DESC LIMIT 2",
        (import_id,),
    )
    jobs = cur.fetchall()
    retry_job = jobs and jobs[0] == (LOAD_KIND, "failed")
    retry_job = retry_job or (
        jobs
        and jobs[0] == (LOAD_KIND, "processing")
        and len(jobs) > 1
        and jobs[1] == (LOAD_KIND, "failed")
    )
    if not retry_job:
        raise LoadError(f"import {import_id} cannot be retried: latest job is not a failed load")

    cur.execute(
        "SELECT detail FROM decision_log WHERE import_id=%s AND step='validation_report' ORDER BY log_id DESC LIMIT 1",
        (import_id,),
    )
    report = cur.fetchone()
    if not report or not (report[0] or {}).get("summary", {}).get("can_proceed", False):
        raise LoadError(f"import {import_id} cannot be retried: latest validation report does not allow proceeding")

    cur.execute(
        """SELECT count(*) FROM source_file
           WHERE import_id=%s            AND file_type IN ('tr_oth','tr_cre','tr_mrk','tr_sov')
             AND to_regclass(%s || '.f' || file_id) IS NULL""",
        (import_id, "staging"),
    )
    missing = cur.fetchone()[0]
    if missing:
        raise LoadError(f"import {import_id} cannot be retried: {missing} data staging table(s) are missing")


def enqueue_load(import_id: int, schema: str | None = None) -> dict:
    conn = connect(schema or get_schema())
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (import_id,))
            row = cur.fetchone()
            if row and row[0] == "loaded":
                raise LoadError(f"import {import_id} is already loaded")
            _check_load_status(cur, import_id)
            cur.execute("SELECT job_id,status FROM job WHERE import_id=%s AND kind=%s AND status IN ('pending','processing') ORDER BY job_id DESC LIMIT 1", (import_id, LOAD_KIND))
            active = cur.fetchone()
            if active:
                return {"job_id": active[0], "status": active[1], "created": False}
            cur.execute("INSERT INTO job(import_id,kind,status,message) VALUES (%s,%s,'pending','queued') RETURNING job_id", (import_id, LOAD_KIND))
            return {"job_id": cur.fetchone()[0], "status": "pending", "created": True}
    finally:
        conn.close()


def run_load(import_id: int, schema: str | None = None, emit=None) -> None:
    schema = schema or get_schema()
    emit = emit or (lambda message, progress: None)
    conn = connect(schema)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM import_batch WHERE import_id=%s FOR UPDATE", (import_id,))
            current = cur.fetchone()
            if not current:
                raise LoadError(f"import {import_id} does not exist")
            if current[0] == "loaded":
                raise LoadError(f"import {import_id} is already loaded")
            _check_load_status(cur, import_id)
            cur.execute("UPDATE import_batch SET status='loading' WHERE import_id=%s", (import_id,))
            versions, timings = _load(cur, import_id, emit)
            cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'load_report',%s)",
                        (import_id, Json({"versions": versions, "timings": timings, "staging_dropped": None})))
            conn.commit()
        dropped = os.getenv("EBA_DROP_STAGING_AFTER_LOAD", "true").lower() != "false"
        if dropped:
            try:
                with conn, conn.cursor() as cur:
                    repo.drop_staging_tables(cur, import_id)
            except Exception:
                dropped = False
        with conn, conn.cursor() as cur:
            cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'load_report',%s)",
                        (import_id, Json({"staging_dropped": dropped})))
    except Exception as exc:
        conn.rollback()
        failed_conn = connect(schema)
        with failed_conn, failed_conn.cursor() as cur:
            cur.execute("UPDATE import_batch SET status='failed' WHERE import_id=%s AND status <> 'loaded'", (import_id,))
        failed_conn.close()
        if isinstance(exc, UniqueViolation):
            constraint = getattr(exc.diag, "constraint_name", "") or ""
            table = next((name for name in ("fact_oth", "fact_cre", "fact_mrk", "fact_sov") if name in constraint), "fact")
            raise LoadError(f"duplicate-facts: {table}") from exc
        raise
    finally:
        conn.close()
