"""Receiving files: size limit, immutable storage, duplicate checks and the registration of an import with a pending job."""
from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import get_max_upload_bytes
from app.core.database import connect
from app.modules.eba_ingest.domain import DuplicateFile, IngestError
from app.modules.eba_ingest.domain.services.file_detector import classify_name
from app.modules.eba_ingest.infrastructure.database import repositories as repo
from app.modules.eba_ingest.infrastructure.storage.storage import store

from app.modules.eba_ingest.config import DEFAULT_MAX_BYTES  # noqa: F401 (re-exported for callers)


@dataclass(frozen=True)
class StoredFile:
    name: str
    sha256: str
    size_bytes: int
    path: str
    encoding: str


def encoding_label(name: str, detected: str) -> str:
    """The encoding shown to users: workbooks are 'xlsx'; csv files are 'utf-8' or 'cp1252'."""
    return "xlsx" if name.lower().endswith(".xlsx") else detected


def remove_files(paths: list[str]) -> None:
    for p in paths:
        try:
            os.chmod(p, 0o644)
            os.remove(p)
        except OSError:
            pass


def store_files(paths, storage_dir: str, max_bytes: int, say=None) -> tuple[list[StoredFile], list[str]]:
    """Stores every file (hash and encoding in one pass). Returns the stored files and the copies created by THIS call.
    On any failure the copies created here are removed before the error propagates."""
    say = say or (lambda message: None)
    stored: list[StoredFile] = []
    created_now: list[str] = []
    try:
        for p in [str(p) for p in paths]:
            name = os.path.basename(p)
            say(f"storing {name}")
            sha, size, final, enc, created = store(p, storage_dir, max_bytes, detect_encoding=p.lower().endswith(".csv"))
            if created:
                created_now.append(final)
            stored.append(StoredFile(name, sha, size, final, encoding_label(name, enc)))
        if len({s.sha256 for s in stored}) != len(stored):
            raise DuplicateFile("the same file was selected twice")
    except Exception:
        remove_files(created_now)
        raise
    return stored, created_now


def check_before_registering(cur, stored: list[StoredFile], user_id: int | None) -> None:
    if user_id is not None and not repo.user_exists(cur, user_id):
        raise IngestError(f"user {user_id} does not exist")
    duplicate = repo.find_loaded_duplicate(cur, [s.sha256 for s in stored])
    if duplicate:
        raise DuplicateFile(f"{duplicate[0]} was already loaded in import {duplicate[1]} (same sha256)")


def register_files(cur, import_id: int, stored: list[StoredFile]) -> None:
    for s in stored:
        repo.add_source_file(cur, import_id, s.name, s.size_bytes, s.sha256, classify_name(s.name) or "unrecognised", s.encoding, s.path)


def enqueue_import(paths, storage_dir: str, user_id: int | None = None, edition_label: str | None = None,
                   max_bytes: int | None = None, schema: str = "public") -> int:
    """Stores the files, registers an import and queues a 'stage' job. The worker does the reading (see staging_service)."""
    max_bytes = max_bytes or get_max_upload_bytes()
    stored, created_now = store_files(paths, storage_dir, max_bytes)
    conn = None
    try:
        conn = connect(schema)
        with conn.cursor() as cur:
            check_before_registering(cur, stored, user_id)
            import_id = repo.create_import(cur, user_id, edition_label)
            register_files(cur, import_id, stored)
            repo.enqueue_job(cur, import_id)
        conn.commit()
        return import_id
    except Exception:
        if conn:
            conn.rollback()
        remove_files(created_now)
        raise
    finally:
        if conn:
            conn.close()
