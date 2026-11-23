"""Reading side of the module: what the interface shows about imports."""
from __future__ import annotations

from app.core.database import connect
from app.modules.eba_ingest.domain.exceptions import StagingInUse  # noqa: F401 (re-exported for callers)
from app.modules.eba_ingest.infrastructure.database import repositories as repo


def drop_staging(import_id: int, schema: str = "public") -> int:
    """Removes the staging tables of an import (after the load or when the import is cancelled). Returns how many were dropped."""
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """SELECT i.status,
                          EXISTS (SELECT 1 FROM job j
                                  WHERE j.import_id=i.import_id
                                    AND j.status IN ('pending','processing'))
                   FROM import_batch i WHERE i.import_id=%s FOR UPDATE""",
                (import_id,),
            )
            row = cur.fetchone()
            if row and (row[0] == "loading" or row[1]):
                raise StagingInUse(f"import {import_id} staging cannot be dropped while a job is active")
            return repo.drop_staging_tables(cur, import_id)
    finally:
        conn.close()


def show(import_id: int, schema: str = "public") -> dict | None:
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            return repo.latest_report(cur, import_id)
    finally:
        conn.close()


def list_imports(schema: str = "public", limit: int = 200) -> list[dict]:
    """One summary per import, newest first."""
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            rows = repo.list_import_rows(cur, limit)
            flags = repo.staging_flags(cur, [r[0] for r in rows])
    finally:
        conn.close()
    return [
        dict(import_id=r[0], status=r[1], edition_label=r[2], created_at=r[3].isoformat(), created_by=r[4], files=r[5], file_names=list(r[6]),
             error=r[7], has_staging=bool(flags.get(r[0], False)), job_status=r[8], progress=r[9] or 0, progress_message=r[10])
        for r in rows
    ]


def get_import(import_id: int, schema: str = "public") -> dict | None:
    """The stored report plus the live state of the import and of its job; None if the import does not exist.
    Before the worker has read the files, `recognised` is None (not inspected yet) instead of a misleading False."""
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            head = repo.import_head(cur, import_id)
            if head is None:
                return None
            stored_report = repo.latest_report(cur, import_id)
            files = repo.source_files(cur, import_id)
            flags = repo.staging_flags(cur, [import_id])
    finally:
        conn.close()
    report = dict(stored_report) if stored_report else dict(
        import_id=import_id, seconds=0.0, error=head[8],
        files=[dict(name=f.name, size_bytes=f.size_bytes, sha256=f.sha256, file_type=f.file_type, recognised=None, encoding=f.encoding, file_id=f.file_id) for f in files],
    )
    report.update(
        import_id=import_id, status=head[0], edition_label=head[1], created_at=head[2].isoformat(), created_by=head[3],
        has_staging=bool(flags.get(import_id, False)), job_id=head[4], job_status=head[5], progress=head[6] or 0, progress_message=head[7],
        error=report.get("error") or head[8],
    )
    return report
