"""Regression test for SMOTE crash when positives < k_neighbors (T-2 fix).

Crash: SMOTE(k_neighbors=5).fit_resample raises ValueError when training fold
has fewer than 6 positive examples.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.modules.eba_ml.application.training.smote import smote_fold_comparison


def _make_model(n_features: int = 3):
    from sklearn.ensemble import RandomForestClassifier
    return RandomForestClassifier(n_estimators=5, random_state=0)


def test_smote_returns_none_when_fewer_than_6_positives():
    """smote_fold_comparison must return None (not raise) when positives < 6."""
    rng = np.random.default_rng(0)
    # 20 train rows, only 3 positives — SMOTE would crash without the guard
    X_train = rng.standard_normal((20, 3))
    y_train = np.zeros(20, dtype=int)
    y_train[:3] = 1  # only 3 positives, k_neighbors=5 needs >= 6
    X_test = rng.standard_normal((5, 3))
    y_test = np.array([1, 0, 0, 0, 0])

    model = _make_model()
    model.fit(X_train, y_train)

    result = smote_fold_comparison(X_train, y_train, X_test, y_test, model, 1, "RF", 42)
    assert result is None


def test_smote_returns_dict_when_enough_positives():
    """smote_fold_comparison returns a result dict when positives >= 6."""
    rng = np.random.default_rng(0)
    # 40 train rows, 10 positives
    X_train = rng.standard_normal((40, 3))
    y_train = np.zeros(40, dtype=int)
    y_train[:10] = 1
    X_test = rng.standard_normal((10, 3))
    y_test = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])

    model = _make_model()
    model.fit(X_train, y_train)

    result = smote_fold_comparison(X_train, y_train, X_test, y_test, model, 1, "RF", 42)
    assert result is not None
    assert "pr_auc" in result
    assert 0.0 <= result["pr_auc"] <= 1.0


def test_smote_returns_none_when_single_class():
    """smote_fold_comparison returns None when training has only one class."""
    rng = np.random.default_rng(0)
    X_train = rng.standard_normal((20, 3))
    y_train = np.zeros(20, dtype=int)
    X_test = rng.standard_normal((5, 3))
    y_test = np.zeros(5, dtype=int)

    model = _make_model()
    model.fit(X_train, y_train)

    result = smote_fold_comparison(X_train, y_train, X_test, y_test, model, 1, "RF", 42)
    assert result is None
