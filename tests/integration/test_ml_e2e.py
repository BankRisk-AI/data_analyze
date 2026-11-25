"""Integration test: ML train (budget=2) + hypotheses --quick end-to-end (§3.5-3.6).

Requires TEST_DATABASE_URL in .env pointing to eba_test with EBA panel data loaded.
Does NOT use the db fixture (which drops schema); connects directly.
"""
from __future__ import annotations
import os
from pathlib import Path

import pytest


_TEST_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def _ml_conn():
    """Direct connection to TEST_DATABASE_URL (must have EBA panel data)."""
    if not _TEST_URL:
        pytest.skip("TEST_DATABASE_URL not configured")
    import psycopg2
    conn = psycopg2.connect(_TEST_URL)
    yield conn
    conn.close()


def test_ml_train_and_hypotheses_quick(_ml_conn, tmp_path):
    """Full pipeline: build_dataset -> build_labels -> train (budget=2) -> hypotheses --quick.

    Runs with wall_clock_hours=2/60 (a 2-minute budget for CI).
    Writes only to tmp_path; no writes to prod/test panel tables.
    Skipped if no EBA panel data is present in TEST_DATABASE_URL.
    """
    import psycopg2
    from app.modules.eba_ml.application.training.train import train
    from app.modules.eba_ml.application.evaluation.hypotheses import hypotheses

    # Quick check: skip if panel_row is empty
    with _ml_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM panel_row")
        n_rows = cur.fetchone()[0]
    if n_rows == 0:
        pytest.skip("eba_test has no panel data; load EBA data first")

    out_dir = tmp_path / "ml_e2e"
    out_dir.mkdir()

    conn = psycopg2.connect(_TEST_URL)
    try:
        result = train(
            conn,
            label="E2_or_E3",
            grid="semiannual",
            out_dir=out_dir,
            robustness=False,
            models=["LR"],
            wall_clock_hours=2.0 / 60,
        )
    finally:
        conn.close()

    # Verify results JSON was written
    result_files = list(out_dir.glob("results_*.json"))
    assert result_files, "No results_*.json written"
    assert result["label"] == "E2_or_E3"
    assert "predictions" in result
    assert "operating_point_threshold" in result
    assert "r1_margin" in result
    assert isinstance(result.get("label_meta"), dict)
    assert result["label_meta"]["n_included"] > 0

    # --- hypotheses --quick ---
    # DATABASE_URL is already TEST_DATABASE_URL (set by pytest_configure)
    report = hypotheses(out_dir, quick=True)

    assert "H1a" in report
    assert "H1b" in report
    assert "H2" in report
    assert "H3" in report
    assert "H5" in report
    assert (out_dir / "hypotheses.json").exists()
