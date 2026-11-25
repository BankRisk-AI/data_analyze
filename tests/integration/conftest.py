"""Integration test guards.

Aborts the session if TEST_DATABASE_URL connects to any database other than
'eba_test', preventing accidental writes to production.
"""
from __future__ import annotations

import os

import psycopg2
import pytest

_TEST_URL = os.getenv("TEST_DATABASE_URL", "")


def pytest_configure(config):
    """Hard guard: abort early if TEST_DATABASE_URL points to non-eba_test DB."""
    if not _TEST_URL:
        return
    try:
        conn = psycopg2.connect(_TEST_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            db_name = cur.fetchone()[0]
        conn.close()
    except Exception:
        return

    if db_name != "eba_test":
        pytest.exit(
            f"SAFETY ABORT: TEST_DATABASE_URL connects to '{db_name}', not 'eba_test'. "
            "Integration tests must not run against a non-test database.",
            returncode=2,
        )
