"""Integration tests for SHAP correctness.

Both tests use the test DB (DATABASE_URL is redirected to TEST_DATABASE_URL
by tests/conftest.py pytest_configure before any test runs).

Run with: pytest tests/integration/test_ml_shap.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_H5_PATH = Path("data/ml/T3_primary/hypotheses.json")


@pytest.mark.skipif(not _H5_PATH.exists(), reason="T3_primary data not available")
def test_model_card_global_shap_matches_h5():
    """Model card global_shap.families must equal H5 primary output (bit-identical).

    Uses DATABASE_URL (redirected to eba_test by pytest_configure).
    Skips if thesis models have not been seeded into the test DB.
    """
    h5 = json.loads(_H5_PATH.read_text())["H5"]
    h5_primary = h5.get("primary", {})

    from app.core.config import get_schema
    from app.core.database import connect

    conn = connect(get_schema())
    cur = conn.cursor()
    cur.execute("SELECT model_card FROM ml_model WHERE name='thesis-T3-primary-lr'")
    row = cur.fetchone()
    conn.close()

    if not row:
        pytest.skip("thesis-T3-primary-lr not in test DB (eba_test not seeded)")
    card = row[0] or {}
    card_families = card.get("global_shap", {}).get("families", {})

    for family, h5_val in h5_primary.items():
        card_val = card_families.get(family)
        assert card_val is not None, f"family {family} missing from model card"
        assert abs(card_val - h5_val) < 1e-12, \
            f"{family}: card={card_val}, H5={h5_val} — not bit-identical"


def test_score_panel_shap_reproducible():
    """Two score_panel runs produce identical SHAP payloads.

    Uses DATABASE_URL (redirected to eba_test by pytest_configure).
    Skips if no champion model in test DB.
    """
    from app.core.config import get_schema
    from app.core.database import connect
    from app.modules.eba_ml.application.worker_handlers import _score

    conn = connect(get_schema())
    cur = conn.cursor()
    cur.execute("SELECT model_id FROM ml_model WHERE status='champion' LIMIT 1")
    if not cur.fetchone():
        conn.close()
        pytest.skip("no champion model in test DB (eba_test not seeded)")
    conn.close()

    class _FakeJob:
        job_id = 1
        schema = get_schema()

    class _FakeProgress:
        def __call__(self, msg, pct):
            pass

    _score(_FakeJob(), _FakeProgress())
    conn = connect(get_schema())
    cur = conn.cursor()
    cur.execute("""SELECT bank_id, period_end, shap FROM ml_prediction
                   WHERE threshold_setting='operating_point_f2' AND shap IS NOT NULL
                   ORDER BY bank_id, period_end""")
    rows_first = [(r[0], r[1], json.dumps(r[2], sort_keys=True)) for r in cur.fetchall()]
    conn.close()

    assert rows_first, "No scored rows after first run"

    _score(_FakeJob(), _FakeProgress())
    conn = connect(get_schema())
    cur = conn.cursor()
    cur.execute("""SELECT bank_id, period_end, shap FROM ml_prediction
                   WHERE threshold_setting='operating_point_f2' AND shap IS NOT NULL
                   ORDER BY bank_id, period_end""")
    rows_second = [(r[0], r[1], json.dumps(r[2], sort_keys=True)) for r in cur.fetchall()]
    conn.close()

    assert len(rows_first) == len(rows_second), "Row count changed between runs"
    for (b1, p1, s1), (b2, p2, s2) in zip(rows_first, rows_second):
        assert b1 == b2 and p1 == p2 and s1 == s2, \
            f"SHAP changed for bank={b1} period={p1}"
