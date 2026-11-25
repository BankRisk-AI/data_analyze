
import os
from pathlib import Path
from types import SimpleNamespace

import psycopg2
import pytest

from dotenv import load_dotenv
from psycopg2 import sql
from app.core.database import init_database


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
SCHEMA = "public"

HEADER = "LEI_Code,NSA,Period,Item,Label,Amount,footnote\n"

_PROD_DB_NAME = "eba"


# ---------------------------------------------------------
# Session-start guard: redirect DATABASE_URL → TEST_DATABASE_URL
# Runs before any test module is imported.
# ---------------------------------------------------------

def pytest_configure(config):
    """Hard guard: redirect DATABASE_URL to TEST_DATABASE_URL for the whole session.

    Aborts if TEST_DATABASE_URL is missing, cannot be contacted, its
    database name is not 'eba_test', or the resolved current_database()
    matches the prod name.
    """
    if not TEST_DATABASE_URL:
        pytest.exit(
            "SAFETY ABORT: TEST_DATABASE_URL is not set. "
            "Tests must not run without a dedicated test database.",
            returncode=2,
        )
    try:
        conn = psycopg2.connect(TEST_DATABASE_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            db_name = cur.fetchone()[0]
        conn.close()
    except Exception as exc:
        pytest.exit(
            f"SAFETY ABORT: Cannot connect to TEST_DATABASE_URL: {exc}",
            returncode=2,
        )
    if db_name != "eba_test":
        pytest.exit(
            f"SAFETY ABORT: TEST_DATABASE_URL resolves to '{db_name}', not 'eba_test'. "
            "Tests must not run against a non-test database.",
            returncode=2,
        )
    # Unconditionally redirect DATABASE_URL for the whole process
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL


# ---------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------

@pytest.fixture(scope="session")
def database_url():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")

    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
            cur.execute("CREATE SCHEMA public")
            cur.execute("CREATE SCHEMA staging")
    finally:
        conn.close()

    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    try:
        init_database(SCHEMA)
        yield TEST_DATABASE_URL
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


# ---------------------------------------------------------
# Per-test database fixture
# ---------------------------------------------------------

@pytest.fixture()
def db(database_url, tmp_path):
    """
    Prepares clean application data and temporary storage
    for every individual test.
    """

    conn = psycopg2.connect(database_url)
    conn.autocommit = True

    cur = conn.cursor()

    cur.execute(
        sql.SQL("SET search_path TO {}, public").format(
            sql.Identifier(SCHEMA)
        )
    )

    cur.execute(
        """
        TRUNCATE
            audit_log,
            decision_log,
            job,
            source_file,
            import_batch,
            app_user
        RESTART IDENTITY CASCADE
        """
    )

    cur.execute(
        """
        INSERT INTO app_user(username, password_hash, role)
        VALUES ('admin', 'x', 'administrator')
        """
    )

    cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    cur.execute("CREATE SCHEMA staging")

    helper = SimpleNamespace(
        cur=cur,
        conn=conn,
        database_url=database_url,
        storage=str(tmp_path / "storage"),
        dir=tmp_path,
        schema=SCHEMA,
    )

    yield helper

    cur.close()
    conn.close()


# ---------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------

def write_csv(path, rows, encoding="cp1252", header=HEADER):
    with open(path, "w", encoding=encoding, newline="") as file:
        file.write(header)

        for row in rows:
            file.write(row + "\n")

    return str(path)
