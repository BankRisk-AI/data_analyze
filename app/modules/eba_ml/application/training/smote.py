"""SMOTE oversampling comparison for one fold (§3.5, robustness check).

Applied inside the OOF loop to compare with-SMOTE vs without-SMOTE PR-AUC.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def smote_fold_comparison(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    model,
    fold_number: int,
    model_name: str,
    seed: int,
) -> dict[str, Any] | None:
    """Fit a SMOTE-oversampled clone and return its fold PR-AUC (§3.5).

    Returns None when the training fold has fewer than 2 classes (SMOTE cannot run).
    """
    from imblearn.over_sampling import SMOTE
    from sklearn.base import clone
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import average_precision_score

    if len(np.unique(y_train)) < 2:
        return None
    imputer = SimpleImputer(strategy="median")
    x_over, y_over = SMOTE(random_state=seed).fit_resample(
        imputer.fit_transform(X_train), y_train
    )
    comparison = clone(model)
    comparison.fit(x_over, y_over)
    test_values = imputer.fit(X_train).transform(X_test)
    probability = comparison.predict_proba(test_values)[:, 1]
    return {
        "fold": fold_number,
        "model": model_name,
        "pr_auc": float(average_precision_score(y_test, probability)),
    }
