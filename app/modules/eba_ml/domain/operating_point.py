"""F2-maximising operating point, frozen on validation OOF (§3.5).

The threshold is chosen on pooled OOF predictions (test years 2017-2021) and
applied unchanged to the final test and all H* functions.
"""
from __future__ import annotations

import numpy as np


def compute_f2_threshold(y: np.ndarray, scores: np.ndarray) -> tuple[float, float]:
    """Threshold maximising F2 on pooled OOF predictions (§3.5).

    F2 weights recall twice as heavily as precision (beta=2).
    Returns (threshold, f2_score).
    """
    from sklearn.metrics import fbeta_score
    thresholds = np.unique(scores)
    best_t = float(thresholds.mean()) if len(thresholds) else 0.5
    best_f2 = -1.0
    for t in thresholds:
        preds = (scores >= t).astype(int)
        f2 = fbeta_score(y, preds, beta=2.0, zero_division=0)
        if f2 > best_f2:
            best_f2 = f2
            best_t = float(t)
    return best_t, float(best_f2)


def freeze_operating_point(
    predictions: dict[str, dict],
    y: np.ndarray,
    key_to_index: dict[str, int],
    selected_model: str,
) -> tuple[float, float]:
    """Freeze operating point from pooled OOF predictions of the selected model (§3.5).

    Returns (threshold, f2_score).
    """
    model_preds = predictions.get(selected_model, {})
    keys = [k for k in model_preds if k in key_to_index]
    if not keys:
        return 0.5, 0.0
    actual = np.asarray([y[key_to_index[k]] for k in keys])
    scores = np.asarray([model_preds[k] for k in keys])
    return compute_f2_threshold(actual, scores)
