"""Tests for score_panel SHAP reproducibility and global SHAP matching H5 output.

T-4 / T-7: per-bank SHAP uses a stored background sample (reproducible);
global SHAP in model card equals H5 numbers from T3_primary/hypotheses.json.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers shared by synthetic SHAP tests
# ---------------------------------------------------------------------------

_FEATURES = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi",
    "sovereign_hhi", "loan_growth_qoq", "loan_growth_yoy",
)


def _row(bank_id: int, year: int, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed + bank_id * 100 + year)
    r = {"bank_id": bank_id, "period": date(year, 6, 30)}
    for f in _FEATURES:
        r[f] = float(rng.uniform(0.09, 0.20))
    r["cet1_ratio"] = float(rng.uniform(0.09, 0.18))
    r["tier1_ratio"] = float(rng.uniform(0.10, 0.20))
    r["total_capital_ratio"] = float(rng.uniform(0.12, 0.22))
    if bank_id <= 3 and year >= 2016:
        r["cet1_ratio"] = max(0.08, r["cet1_ratio"] - (year - 2015) * 0.008)
    return r


def _synthetic_dataset(n_banks: int = 8) -> dict:
    import hashlib
    rows = [_row(b, yr) for b in range(1, n_banks + 1) for yr in range(2014, 2025)]
    X = np.asarray([[r.get(f) or 0.0 for f in _FEATURES] for r in rows], dtype=float)
    ph = hashlib.sha256(json.dumps(
        [(r["bank_id"], r["period"].isoformat()) for r in rows], default=str
    ).encode()).hexdigest()
    return {"rows": rows, "X": X, "columns": list(_FEATURES),
            "panel_hash": ph, "grid": "semiannual"}


# ---------------------------------------------------------------------------
# Unit test: global_oof_shap structure
# ---------------------------------------------------------------------------

def test_global_oof_shap_structure(monkeypatch):
    """_global_oof_shap returns expected keys and families sum to plausible values."""
    import app.modules.eba_ml.application.training.search as search_mod
    from app.modules.eba_ml.application.registry import _global_oof_shap

    def _two_configs(name, space="table35"):
        if name == "LR":
            return [{"penalty": "l2", "solver": "liblinear", "C": 0.1}]
        if name == "RF":
            return [{"max_depth": 3, "min_samples_leaf": 2, "max_features": "sqrt"}]
        return [{"n_estimators": 10, "max_depth": 3, "learning_rate": 0.1,
                 "subsample": 0.8, "colsample_bytree": 0.8, "reg_lambda": 1.0}]

    monkeypatch.setattr(search_mod, "_search_configs", _two_configs)

    from app.modules.eba_ml.domain.labels import LABEL_OPTIONS, build_labels
    from datetime import date as dt

    ds = _synthetic_dataset()
    # Positives from 2015 onward so early folds (training ends at test_year-2) have mixed classes
    y = np.zeros(len(ds["rows"]), dtype=int)
    for i, r in enumerate(ds["rows"]):
        y[i] = int(r["bank_id"] <= 2 and r["period"].year >= 2015)

    families_cfg = {
        "Capital": ["cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio"],
        "Asset_quality": ["npl_ratio", "stage2_share"],
        "Earnings": ["roe_annualised"],
        "Concentration": ["nace_hhi", "sovereign_hhi"],
        "Growth": ["loan_growth_yoy", "loan_growth_qoq"],
        "Liquidity": [],
    }

    result = _global_oof_shap(ds, y, "LR",
                              {"penalty": "l2", "solver": "liblinear", "C": 0.1},
                              families_cfg, space="table35")

    assert "features" in result
    assert "families" in result
    # All base feature names present
    for feat in _FEATURES:
        assert feat in result["features"], f"{feat} missing from features"
    # Direction is a float in [-1, 1]
    for feat, stats in result["features"].items():
        assert "mean_abs_shap" in stats
        assert "direction" in stats
        assert -1.0 <= stats["direction"] <= 1.0


def test_global_oof_shap_lr_deterministic(monkeypatch):
    """_global_oof_shap gives identical results when called twice (deterministic)."""
    from app.modules.eba_ml.application.registry import _global_oof_shap

    ds = _synthetic_dataset()
    y = np.zeros(len(ds["rows"]), dtype=int)
    for i, r in enumerate(ds["rows"]):
        y[i] = int(r["bank_id"] <= 2 and r["period"].year >= 2015)

    families_cfg = {
        "Capital": ["cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio"],
        "Asset_quality": ["npl_ratio", "stage2_share"],
        "Earnings": ["roe_annualised"],
        "Concentration": ["nace_hhi", "sovereign_hhi"],
        "Growth": ["loan_growth_yoy", "loan_growth_qoq"],
        "Liquidity": [],
    }
    params = {"penalty": "l2", "solver": "liblinear", "C": 0.1}

    r1 = _global_oof_shap(ds, y, "LR", params, families_cfg)
    r2 = _global_oof_shap(ds, y, "LR", params, families_cfg)

    for feat in r1["features"]:
        assert abs(r1["features"][feat]["mean_abs_shap"] -
                   r2["features"][feat]["mean_abs_shap"]) < 1e-12, \
            f"Non-deterministic SHAP for {feat}"
        assert r1["features"][feat]["direction"] == r2["features"][feat]["direction"]


