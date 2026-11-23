from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import psycopg2.errors
import yaml

from app.core.database import connect
from app.core.exceptions import AppError, InvalidParameter, NotFoundError
from app.modules.eba_public_analysis.domain.constants import QUERY_TIMEOUT_SECONDS
from app.modules.eba_public_analysis.domain import MAX_PAGE_SIZE


class QueryTooSlow(AppError):
    kind = "query-too-slow"
    status = 504
    title = "Query too slow"


@contextmanager
def read_session(schema: str):
    conn = connect(schema)
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = %s", (f"{QUERY_TIMEOUT_SECONDS}s",))
        yield conn, cur
    except psycopg2.errors.QueryCanceled as exc:
        raise QueryTooSlow(f"the query took more than {QUERY_TIMEOUT_SECONDS} seconds") from exc
    finally:
        conn.rollback()
        conn.close()


def specialist_leis() -> set[str]:
    path = Path("config/specialist_institutions.yaml")
    return {str(item["lei"]).strip() for item in yaml.safe_load(path.read_text()) or []} if path.exists() else set()


def ensure_active(cur, version_id: int) -> None:
    cur.execute("SELECT 1 FROM dataset_version WHERE version_id=%s AND is_active", (version_id,))
    if not cur.fetchone():
        raise NotFoundError(f"active version {version_id} does not exist")


def validate_page(page: int, page_size: int) -> None:
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise InvalidParameter(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
