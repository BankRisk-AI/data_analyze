"""Synthetic end-to-end test: train() + hypotheses() without a database (T-2).

Builds a minimal in-memory panel, injects it via `dataset=`, patches
_search_configs at the import site in search.py (budget=2), runs quick mode.
No DB required; must pass in CI before any real run.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest

_FEATURES = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi",
    "sovereign_hhi", "loan_growth_qoq", "loan_growth_yoy",
)
R0 = {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105}


def _row(bank_id, period, seed=0):
    rng = np.random.default_rng(seed + bank_id * 100 + period.year * 10 + period.month)
    r = {"bank_id": bank_id, "period": period}
    for name in _FEATURES:
        r[name] = float(rng.uniform(0.09, 0.20))
    r["cet1_ratio"] = float(rng.uniform(0.09, 0.18))
    r["tier1_ratio"] = float(rng.uniform(0.10, 0.20))
    r["total_capital_ratio"] = float(rng.uniform(0.12, 0.22))
    # Banks 1-5: gradual CET1 decline to generate E2 positives
    if bank_id <= 5 and period.year >= 2016:
        r["cet1_ratio"] = max(0.08, r["cet1_ratio"] - (period.year - 2015) * 0.008)
    return r


def _make_panel(n_banks=10):
    rows = []
    for b in range(1, n_banks + 1):
        for year in range(2014, 2025):
            for month in (6, 12):
                rows.append(_row(b, date(year, month, 30), seed=b))
    return rows


def _dataset(rows):
    import hashlib
    X = np.asarray([[r.get(f) or 0.0 for f in _FEATURES] for r in rows], dtype=float)
    ph = hashlib.sha256(
        json.dumps([(r["bank_id"], r["period"].isoformat()) for r in rows],
                   default=str).encode()).hexdigest()
    return {"rows": rows, "X": X, "columns": list(_FEATURES),
            "panel_hash": ph, "grid": "semiannual", "robustness": True}


def _two_configs(name, space="table35"):
    """Minimal 2-config version of _search_configs for fast tests."""
    if name == "LR":
        return [{"penalty": "l2", "solver": "liblinear", "C": 0.1},
                {"penalty": "l1", "solver": "liblinear", "C": 1.0}]
    if name == "RF":
        return [{"max_depth": 3, "min_samples_leaf": 2, "max_features": "sqrt"},
                {"max_depth": 5, "min_samples_leaf": 1, "max_features": "log2"}]
    return [{"n_estimators": 50, "max_depth": 3, "learning_rate": 0.1,
             "subsample": 0.8, "colsample_bytree": 0.8, "reg_lambda": 1.0},
            {"n_estimators": 50, "max_depth": 4, "learning_rate": 0.05,
             "subsample": 0.9, "colsample_bytree": 0.9, "reg_lambda": 0.1}]


def test_train_synthetic_e2_or_e3(tmp_path, monkeypatch):
    """train() with injected dataset + 2-config search completes end-to-end."""
    import app.modules.eba_ml.application.training.search as search_mod
    monkeypatch.setattr(search_mod, "_search_configs", _two_configs)

    from app.modules.eba_ml.application.training.train import train

    rows = _make_panel()
    ds = _dataset(rows)

    result = train(conn=None, label="E2_or_E3", out_dir=str(tmp_path),
                   wall_clock_hours=1.0, space="table35", dataset=ds)

    assert result["label"] == "E2_or_E3"
    assert "predictions" in result
    assert "operating_point_threshold" in result
    assert "r1_margin" in result
    assert len(result.get("rows", [])) > 0
    assert (tmp_path / "search.json").exists()


def test_train_unknown_label_raises(tmp_path):
    """train() raises ValueError for unrecognised label (service 422 boundary)."""
    from app.modules.eba_ml.application.training.train import train
    rows = _make_panel()
    ds = _dataset(rows)
    with pytest.raises(ValueError, match="unknown label"):
        train(conn=None, label="BOGUS", out_dir=str(tmp_path), dataset=ds)


def test_service_validate_unknown_label():
    """service._validate raises InvalidParameter for unknown label."""
    from app.core.exceptions import InvalidParameter
    from app.modules.eba_ml.application.service import _validate
    with pytest.raises(InvalidParameter, match="unknown label"):
        _validate({"grid": "semiannual", "feature_set": "robustness_v1",
                   "algorithms": ["LR"], "label": "BOGUS"})


def test_service_validate_unknown_tail_quantile():
    """service._validate raises InvalidParameter for disallowed tail_quantile."""
    from app.core.exceptions import InvalidParameter
    from app.modules.eba_ml.application.service import _validate
    with pytest.raises(InvalidParameter, match="unknown tail_quantile"):
        _validate({"grid": "semiannual", "feature_set": "robustness_v1",
                   "algorithms": ["LR"], "label": "E2_or_E3", "tail_quantile": 0.50})


def test_service_validate_allowed_tail_quantile():
    """service._validate accepts known tail_quantile values without error."""
    from app.modules.eba_ml.application.service import _validate
    for q in (0.90, 0.95, 0.975, 0.99):
        _validate({"grid": "semiannual", "feature_set": "robustness_v1",
                   "algorithms": ["LR"], "label": "E2_or_E3", "tail_quantile": q})


def test_hypotheses_synthetic_quick(tmp_path, monkeypatch):
    """hypotheses() --quick completes on a synthetic JSON with mocked DB."""
    import app.modules.eba_ml.application.training.search as search_mod
    monkeypatch.setattr(search_mod, "_search_configs", _two_configs)

    rows = _make_panel()
    ds = _dataset(rows)

    # Patch build_dataset in context.py (the import-site, not the source module)
    import app.modules.eba_ml.application.evaluation.context as ctx_mod
    monkeypatch.setattr(ctx_mod, "build_dataset", lambda conn, grid="semiannual", robustness=False: ds)

    # Patch connect in hypotheses.py
    import app.modules.eba_ml.application.evaluation.hypotheses as hyp_mod

    class _FakeConn:
        def cursor(self): return _FakeCur()
        def close(self): pass

    class _FakeCur:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, *a, **kw): pass
        def fetchone(self): return None
        def fetchall(self): return []

    monkeypatch.setattr(hyp_mod, "connect", lambda schema: _FakeConn())
    monkeypatch.setattr(hyp_mod, "get_schema", lambda: "public")

    # Build a minimal results JSON using train()
    from app.modules.eba_ml.application.training.train import train
    result = train(conn=None, label="E2_or_E3", out_dir=str(tmp_path),
                   wall_clock_hours=1.0, space="table35", dataset=ds)

    from app.modules.eba_ml.application.evaluation.hypotheses import hypotheses
    report = hypotheses(tmp_path, quick=True)

    assert "H1a" in report
    assert "H1b" in report
    assert "H2" in report
    assert "H3" in report
    assert "H5" in report
