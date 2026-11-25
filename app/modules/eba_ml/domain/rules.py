"""R0/R1 benchmark alert rules (Table 3.8).

R0: at least one capital ratio below alert level.
R1: at least one ratio below (alert level + margin).
choose_r1_margin: maximises F2 over the margin grid on training rows.
"""
from __future__ import annotations

import numpy as np

from app.modules.eba_ml.domain.labels import _any_breach


def r0_alert(row: dict, r0_levels: dict) -> bool:
    """R0 alert: row is non-compliant (at least one ratio below alert level)."""
    return _any_breach(row, r0_levels)


def r1_alert(row: dict, r0_levels: dict, margin: float) -> bool:
    """R1 alert: at least one ratio below (alert level + margin).

    margin is in fraction units (e.g. 0.01 = 1 pp).
    """
    if not (row.get("cet1_ratio") is not None and row.get("tier1_ratio") is not None and
            row.get("total_capital_ratio") is not None):
        return False
    return (row["cet1_ratio"] < r0_levels["cet1"] + margin or
            row["tier1_ratio"] < r0_levels["tier1"] + margin or
            row["total_capital_ratio"] < r0_levels["total_capital"] + margin)


def choose_r1_margin(
    rows: list[dict],
    y: np.ndarray,
    r0_levels: dict,
    margins_pp: list[float],
) -> tuple[float, float]:
    """Choose R1 margin maximising F2 over margins_pp grid on training rows.

    margins_pp: list of margins in percentage points (e.g. [0.0, 0.5, ..., 10.0]).
    Returns (best_margin_fraction, best_f2).
    """
    from sklearn.metrics import fbeta_score
    best_margin, best_f2 = 0.0, -1.0
    for m_pp in margins_pp:
        margin = m_pp / 100.0
        preds = np.asarray([int(r1_alert(row, r0_levels, margin)) for row in rows])
        f2 = fbeta_score(y, preds, beta=2.0, zero_division=0)
        if f2 > best_f2:
            best_f2 = f2
            best_margin = margin
    return best_margin, float(best_f2)
