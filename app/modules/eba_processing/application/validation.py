"""Use cases: queue a validation, read its state and report, and run it (the worker calls run_validation)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from psycopg2 import sql

from app.core.config import get_schema
from app.core.database import connect
from app.core.logging import get_logger
from app.modules.eba_processing.application.session import read_session
from app.modules.eba_processing.domain import RULES, FileValidation, ImportNotFound, NothingToValidate, ValidationReport
from app.modules.eba_processing.infrastructure import jobs
from app.modules.eba_processing.infrastructure.datasets import import_exists, list_datasets
from app.modules.eba_processing.infrastructure.validation_sql import RULE_FUNCTIONS


logger = get_logger(__name__)


def report_to_dict(r: ValidationReport) -> dict:
    return {
        "import_id": r.import_id, "generated_at": r.generated_at, "seconds": r.seconds,
        "summary": {"errors": r.errors, "warnings": r.warnings, "infos": r.infos, "can_proceed": r.can_proceed},
        "files": [
            {"file_id": f.file_id, "file_name": f.file_name, "file_type": f.file_type, "rows": f.rows,
             "errors": f.count("error"), "warnings": f.count("warning"), "infos": f.count("info"),
             "issues": [{"rule": i.rule, "title": i.title, "severity": i.severity, "status": "passed" if i.passed else "failed",
                         "affected_rows": i.affected_rows, "detail": i.detail, "examples": i.examples, "seconds": i.seconds} for i in f.issues]}
            for f in r.files
        ],
    }


def enqueue_validation(import_id: int, schema: str | None = None) -> dict:
    """Queues a validation job; if one is already waiting or running for the import, that one is returned (`created` is False)."""
    schema = schema or get_schema()
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            if not import_exists(cur, import_id):
                raise ImportNotFound(f"import {import_id} does not exist")
            active = jobs.active_job(cur, import_id)
            if active:
                return {"job_id": active[0], "status": active[1], "created": False}
            if not list_datasets(cur, import_id):
                raise NothingToValidate(f"import {import_id} has no staging tables (dropped or never loaded)")
            return {"job_id": jobs.enqueue(cur, import_id), "status": "pending", "created": True}
    finally:
        conn.close()


def get_validation(import_id: int, schema: str | None = None) -> dict:
    schema = schema or get_schema()
    with read_session(schema) as (cur, _):
        if not import_exists(cur, import_id):
            raise ImportNotFound(f"import {import_id} does not exist")
        return {"import_id": import_id, "import_status": jobs.import_status(cur, import_id), "job": jobs.latest_job(cur, import_id), "report": jobs.latest_report(cur, import_id)}


def run_validation(import_id: int, schema: str | None = None, emit=None) -> ValidationReport:
    """Runs every rule on every staged data file of the import, stores the report and moves the import between 'uploaded' and 'validated'.
    `emit(message, percent)` is called BEFORE any write (progress uses other connections and would wait for locks)."""
    schema = schema or get_schema()
    emit = emit or (lambda message, percent: None)
    started = time.perf_counter()
    logger.info("validation started import_id=%s", import_id)
    conn = connect(schema)
    try:
        cur = conn.cursor()
        datasets = list_datasets(cur, import_id)
        if not datasets:
            raise NothingToValidate(f"import {import_id} has no staging tables (dropped or never loaded)")
        report = ValidationReport(import_id=import_id)
        steps, done = len(datasets) * len(RULES), 0
        for ds in datasets:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(ds.table))
            fv = FileValidation(ds.file_id, ds.file_name, ds.file_type, cur.fetchone()[0])
            for rule_id, fn in RULE_FUNCTIONS:
                emit(f"{ds.file_name}: {rule_id}", 5 + int(90 * done / steps))
                rule_started = time.perf_counter()
                issue = fn(cur, ds)
                issue.seconds = round(time.perf_counter() - rule_started, 2)
                fv.issues.append(issue)
                done += 1
            report.files.append(fv)
        report.generated_at = datetime.now(timezone.utc).isoformat()
        report.seconds = round(time.perf_counter() - started, 2)
        jobs.save_report(cur, import_id, report_to_dict(report))
        jobs.set_status_after_validation(cur, import_id, report.can_proceed)
        conn.commit()
        logger.info("validation completed import_id=%s duration_ms=%.2f", import_id, (time.perf_counter() - started) * 1000)
        return report
    except Exception:
        logger.exception("validation failed import_id=%s", import_id)
        conn.rollback()
        raise
    finally:
        conn.close()
