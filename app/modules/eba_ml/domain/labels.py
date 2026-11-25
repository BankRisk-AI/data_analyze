"""Target label construction for eba_ml (§3.5, Table 3.5, Fig. 3.4).

E1: compliant at t, any R0 breach in (t, t+horizon_months].
E2: compliant at t, CET1(t+12m) - CET1(t) <= -threshold_E2 (forward decline).
E3: compliant at t, NPL(t+12m) - NPL(t) >= threshold_E3 (forward increase).
E2_or_E3: union; E3 excluded when forward window [t, t+12m] spans NPL series break.

Tail thresholds are computed from forward changes of compliant training rows
with period.year <= train_cutoff_year that have a t+12m observation.
Prediction sample = compliant rows with an evaluable forward label.
"""
from __future__ import annotations

from datetime import date

import numpy as np

LABEL_OPTIONS = ("E1", "E2", "E3", "E2_or_E3")


def _add_months(d: date, n: int) -> date:
    import calendar
    total = d.year * 12 + d.month - 1 + n
    y, m = divmod(total, 12)
    day = min(d.day, calendar.monthrange(y, m + 1)[1])
    return date(y, m + 1, day)


def _ratios_present(row: dict) -> bool:
    return (row.get("cet1_ratio") is not None and
            row.get("tier1_ratio") is not None and
            row.get("total_capital_ratio") is not None)


def compliant(row: dict, r0_levels: dict) -> bool:
    """R0-compliant: all three capital ratios present and >= alert levels (§3.5)."""
    return (_ratios_present(row) and
            row["cet1_ratio"] >= r0_levels["cet1"] and
            row["tier1_ratio"] >= r0_levels["tier1"] and
            row["total_capital_ratio"] >= r0_levels["total_capital"])


def _any_breach(row: dict, r0_levels: dict) -> bool:
    return (_ratios_present(row) and
            (row["cet1_ratio"] < r0_levels["cet1"] or
             row["tier1_ratio"] < r0_levels["tier1"] or
             row["total_capital_ratio"] < r0_levels["total_capital"]))


def _forward_four_q_change(row: dict, field: str, by_bank_period: dict) -> float | None:
    """Value at t+12m minus value at t (forward 4-quarter change; positive = increase)."""
    next_period = _add_months(row["period"], 12)
    next_row = by_bank_period.get((row["bank_id"], next_period))
    if next_row is None:
        return None
    v0, v1 = row.get(field), next_row.get(field)
    if v0 is None or v1 is None:
        return None
    return v1 - v0


def compute_tail_threshold(values: list[float], quantile: float) -> float:
    """Quantile of values list (linear interpolation)."""
    if not values:
        return float("nan")
    arr = sorted(values)
    idx = quantile * (len(arr) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(arr) - 1)
    return arr[lo] + (idx - lo) * (arr[hi] - arr[lo])


def class_weight(y: np.ndarray) -> float:
    """Inverse-frequency positive class weight for imbalanced datasets."""
    positives = int(y.sum())
    return float(len(y) - positives) / positives if positives else 1.0


def build_labels(
    rows: list[dict],
    label_name: str,
    tail_quantile: float,
    horizon_months: int,
    r0_levels: dict,
    npl_break: date,
    train_cutoff_year: int = 2020,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Build label array and prediction-sample mask (§3.5, forward-looking).

    Returns (y, included, metadata):
      y: int array aligned to rows; -1 for excluded, 0/1 for labeled rows.
      included: bool array; True where row is in prediction sample.
      metadata: dict with thresholds, counts, excluded_counts.
    Tail thresholds computed from forward changes of compliant training rows
    (period.year <= train_cutoff_year) that have a t+12m observation.
    """
    if label_name not in LABEL_OPTIONS:
        raise ValueError(f"unknown label: {label_name}. Options: {LABEL_OPTIONS}")

    by_bank: dict[int, list[dict]] = {}
    by_bank_period: dict[tuple, dict] = {}
    for row in rows:
        by_bank.setdefault(row["bank_id"], []).append(row)
        by_bank_period[(row["bank_id"], row["period"])] = row
    for bank_rows in by_bank.values():
        bank_rows.sort(key=lambda r: r["period"])

    # Compute tail thresholds from training rows only (forward changes)
    train_compliant = [
        r for r in rows
        if r["period"].year <= train_cutoff_year and compliant(r, r0_levels)
    ]
    cet1_changes = [
        dc for r in train_compliant
        if (dc := _forward_four_q_change(r, "cet1_ratio", by_bank_period)) is not None
    ]
    npl_changes = [
        dn for r in train_compliant
        if (dn := _forward_four_q_change(r, "npl_ratio", by_bank_period)) is not None
    ]
    # E2 threshold: tail of forward CET1 declines (decline = -forward_change)
    cet1_decline_threshold = compute_tail_threshold([-dc for dc in cet1_changes], tail_quantile)
    npl_increase_threshold = compute_tail_threshold(npl_changes, tail_quantile)

    y = np.full(len(rows), -1, dtype=int)
    included = np.zeros(len(rows), dtype=bool)
    excluded_counts: dict[str, int] = {}

    for i, row in enumerate(rows):
        if not compliant(row, r0_levels):
            excluded_counts["non_compliant"] = excluded_counts.get("non_compliant", 0) + 1
            continue

        label: int | None = None
        excl_reason: str | None = None

        if label_name == "E1":
            label, excl_reason = _e1(row, by_bank, r0_levels, horizon_months)
        elif label_name == "E2":
            label, excl_reason = _e2(row, by_bank_period, cet1_decline_threshold)
        elif label_name == "E3":
            label, excl_reason = _e3(row, by_bank_period, npl_increase_threshold, npl_break)
        elif label_name == "E2_or_E3":
            label, excl_reason = _e2_or_e3(
                row, by_bank_period, cet1_decline_threshold, npl_increase_threshold, npl_break)

        if label is None:
            excluded_counts[excl_reason or "other"] = (
                excluded_counts.get(excl_reason or "other", 0) + 1)
        else:
            y[i] = label
            included[i] = True

    metadata = {
        "cet1_decline_threshold": float(cet1_decline_threshold),
        "npl_increase_threshold": float(npl_increase_threshold),
        "tail_quantile": tail_quantile,
        "train_cutoff_year": train_cutoff_year,
        "n_train_compliant": len(train_compliant),
        "n_cet1_changes": len(cet1_changes),
        "n_npl_changes": len(npl_changes),
        "n_included": int(included.sum()),
        "n_positive": int((y == 1).sum()),
        "excluded_counts": excluded_counts,
        "r0_levels": r0_levels,
    }
    return y, included, metadata


def _e1(row: dict, by_bank: dict, r0_levels: dict, horizon_months: int):
    """E1: compliant at t, any R0 breach in (t, t+horizon_months]."""
    horizon_end = _add_months(row["period"], horizon_months)
    future = [x for x in by_bank[row["bank_id"]]
              if row["period"] < x["period"] <= horizon_end]
    if not future:
        already = any(_any_breach(x, r0_levels) for x in by_bank[row["bank_id"]]
                      if x["period"] <= row["period"])
        return (1, None) if already else (None, "no_future")
    return (1 if any(_any_breach(x, r0_levels) for x in future) else 0), None


def _e2(row: dict, by_bank_period: dict, threshold: float):
    """E2: CET1(t+12m) - CET1(t) <= -threshold (forward decline)."""
    dc = _forward_four_q_change(row, "cet1_ratio", by_bank_period)
    if dc is None:
        return None, "no_future_cet1"
    return (1 if -dc >= threshold else 0), None


def _e3(row: dict, by_bank_period: dict, threshold: float, npl_break: date):
    """E3: NPL(t+12m) - NPL(t) >= threshold (forward increase).

    Excluded if forward window [t, t+12m] spans the NPL series break.
    """
    next_period = _add_months(row["period"], 12)
    if row["period"] < npl_break <= next_period:
        return None, "npl_break"
    dn = _forward_four_q_change(row, "npl_ratio", by_bank_period)
    if dn is None:
        return None, "no_future_npl"
    return (1 if dn >= threshold else 0), None


def _e2_or_e3(row: dict, by_bank_period: dict, cet1_thr: float, npl_thr: float, npl_break: date):
    """E2_or_E3: 1 if E2=1 or E3=1; break rows use E2 only."""
    e2_label, e2_excl = _e2(row, by_bank_period, cet1_thr)
    e3_label, e3_excl = _e3(row, by_bank_period, npl_thr, npl_break)

    if e3_excl == "npl_break":
        return e2_label, (None if e2_label is not None else e2_excl)
    if e2_label is None and e3_label is None:
        return None, e2_excl or e3_excl
    if e2_label is None:
        return e3_label, None
    if e3_label is None:
        return e2_label, None
    return (1 if (e2_label == 1 or e3_label == 1) else 0), None
