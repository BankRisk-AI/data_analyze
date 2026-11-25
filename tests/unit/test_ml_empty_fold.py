"""Tests for dtype safety when a label excludes all rows in a fold year.

E3 excludes all 2019 rows via npl_break; folds() must return int dtype arrays
even for empty lists so that y[test_indices] does not raise IndexError.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.training.assembly import build_split_report


def _make_rows(years: list[int]) -> list[dict]:
    return [{"bank_id": f"B{i:03d}", "period": date(yr, 6, 30)}
            for i, yr in enumerate(years)]


def test_folds_returns_int_dtype_for_empty_year():
    """folds() must return int-dtype arrays even when no rows fall in a test year."""
    # Rows for all fold years except 2019 — simulates E3 npl_break exclusion
    years = [y for y in range(2014, 2025) if y != 2019]
    rows = _make_rows(years)
    result = folds(rows)
    for train_idx, test_idx in result:
        assert train_idx.dtype == np.dtype(int), f"train dtype: {train_idx.dtype}"
        assert test_idx.dtype == np.dtype(int), f"test dtype: {test_idx.dtype}"


def test_build_split_report_skips_empty_test_fold():
    """build_split_report must skip folds with zero test rows instead of crashing."""
    years = [y for y in range(2014, 2025) if y != 2019]
    rows = _make_rows(years)
    y = np.zeros(len(rows), dtype=int)
    y[0] = 1  # at least one positive so metrics are computable
    # Must not raise; returns 4 OOF fold entries (2017,2018,2020,2021) + final_test
    final_train_idx = np.asarray(
        [i for i, r in enumerate(rows) if r["period"].year <= 2020], dtype=int)
    final_test_idx = np.asarray(
        [i for i, r in enumerate(rows) if r["period"].year >= 2022], dtype=int)
    report = build_split_report(rows, y, final_train_idx, final_test_idx)
    fold_numbers = [r["fold"] for r in report]
    assert 2019 not in fold_numbers, "empty 2019 fold should be skipped"
    assert "final_test" in fold_numbers


def test_folds_non_empty_year_is_int():
    """Positive control: folds() with all years present also returns int dtype."""
    years = list(range(2014, 2025))
    rows = _make_rows(years)
    result = folds(rows)
    for train_idx, test_idx in result:
        assert train_idx.dtype == np.dtype(int)
        assert test_idx.dtype == np.dtype(int)
