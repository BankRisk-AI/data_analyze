"""Threshold computation for alert calibration.

Computes score thresholds that match a given alert share (§3.4).
"""
from __future__ import annotations

import numpy as np


def matched_far_threshold(scores: np.ndarray, alert_share: float) -> float:
    """Return quantile that matches the comparator's alert share (Table 3.4).

    alert_share: fraction of periods with at least one rule alert.
    """
    return float(np.quantile(scores, max(0.0, 1.0 - alert_share)))


def max_ur_threshold(scores: np.ndarray, quantile: float = 0.90) -> float:
    """Return the top-decile threshold for uniform recall (§3.4)."""
    return float(np.quantile(scores, quantile))


def compute_thresholds(scores: np.ndarray, alert_share: float) -> dict:
    """Return both thresholds used in event matching (Table 3.4)."""
    return {
        "matched_far": matched_far_threshold(scores, alert_share),
        "max_ur_0_9": max_ur_threshold(scores),
    }
