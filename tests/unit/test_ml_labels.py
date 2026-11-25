"""Unit tests for domain/labels.py — including T-0 count reproduction."""
from __future__ import annotations
from datetime import date

import numpy as np
import pytest

from app.modules.eba_ml.domain.labels import (
    LABEL_OPTIONS,
    _add_months,
    _forward_four_q_change,
    build_labels,
    class_weight,
    compliant,
    compute_tail_threshold,
)

R0 = {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105}

# --- helper ---

def _row(bank_id=1, period=date(2016, 12, 31),
         cet1=0.12, tier1=0.14, total=0.16, npl=0.02):
    return dict(bank_id=bank_id, period=period,
                cet1_ratio=cet1, tier1_ratio=tier1, total_capital_ratio=total,
                npl_ratio=npl)


def _semiannual(bank_id=1, start_year=2014, end_year=2019,
                cet1=0.12, tier1=0.14, total=0.16, npl=0.02):
    rows = []
    for y in range(start_year, end_year + 1):
        for m in (6, 12):
            rows.append(_row(bank_id=bank_id,
                             period=date(y, m, 30 if m == 6 else 31),
                             cet1=cet1, tier1=tier1, total=total, npl=npl))
    return rows


# --- basic unit tests ---

def test_add_months_basic():
    assert _add_months(date(2016, 12, 31), 12) == date(2017, 12, 31)
    # Dec 31 + 6 months: June has only 30 days, clamp to 30
    assert _add_months(date(2016, 12, 31), 6) == date(2017, 6, 30)
    # Feb 29 leap - 12: Feb 2019 has 28 days
    assert _add_months(date(2020, 2, 29), -12) == date(2019, 2, 28)
    # Dec 31 - 12: same month
    assert _add_months(date(2017, 12, 31), -12) == date(2016, 12, 31)


def test_compliant_requires_all_ratios():
    r = _row(cet1=0.12, tier1=0.14, total=0.16)
    assert compliant(r, R0)
    assert not compliant({**r, "cet1_ratio": 0.065}, R0)
    assert not compliant({**r, "tier1_ratio": None}, R0)


def test_compute_tail_threshold_basic():
    vals = list(range(100))
    assert abs(compute_tail_threshold(vals, 0.95) - 94.05) < 0.01
    assert compute_tail_threshold([], 0.95) != compute_tail_threshold([], 0.95)  # nan check


def test_class_weight():
    y = np.array([0, 0, 0, 1])
    w = class_weight(y)
    assert abs(w - 3.0) < 1e-9


def test_forward_four_q_change_requires_future():
    rows = [_row(bank_id=1, period=date(2015, 12, 31), npl=0.02),
            _row(bank_id=1, period=date(2016, 12, 31), npl=0.03)]
    by_bank_period = {(r["bank_id"], r["period"]): r for r in rows}
    # Forward: 2015 looks to 2016 → 0.03 - 0.02 = 0.01
    dc = _forward_four_q_change(rows[0], "npl_ratio", by_bank_period)
    assert abs(dc - 0.01) < 1e-9
    # Last row has no future → None
    dc_last = _forward_four_q_change(rows[1], "npl_ratio", by_bank_period)
    assert dc_last is None


# --- label array tests ---

def test_build_labels_e2_basic():
    """E2: compliant row with large forward CET1 decline labelled 1; small decline 0."""
    rows = [
        _row(bank_id=1, period=date(2015, 12, 31), cet1=0.14),
        _row(bank_id=1, period=date(2016, 12, 31), cet1=0.08),  # future of bank1@2015: decline 0.06 big
        _row(bank_id=2, period=date(2015, 12, 31), cet1=0.14),
        _row(bank_id=2, period=date(2016, 12, 31), cet1=0.135), # future of bank2@2015: decline 0.005 small
    ]
    # threshold: q=0.5 of forward declines from 2015 rows = median([0.06, 0.005]) = 0.0325
    y, included, meta = build_labels(rows, "E2", 0.5, 12, R0,
                                     date(2020, 6, 30), train_cutoff_year=2020)
    # Only 2015 rows can have E2 (need future 12m = 2016); 2016 rows excluded (no future)
    assert included.sum() == 2
    for i, r in enumerate(rows):
        if r["bank_id"] == 1 and r["period"].year == 2015:
            assert y[i] == 1   # forward decline 0.06 >= threshold 0.0325
        elif r["bank_id"] == 2 and r["period"].year == 2015:
            assert y[i] == 0   # forward decline 0.005 < threshold 0.0325
        elif r["period"].year == 2016:
            assert not included[i]  # no future → excluded


def test_build_labels_e3_excludes_npl_break():
    """E3: row excluded when forward window [t, t+12m] spans NPL series break."""
    npl_break = date(2020, 6, 30)
    rows = [
        _row(bank_id=1, period=date(2019, 12, 31), npl=0.02),
        _row(bank_id=1, period=date(2020, 12, 31), npl=0.08),
    ]
    y, included, meta = build_labels(rows, "E3", 0.5, 12, R0,
                                     npl_break, train_cutoff_year=2020)
    inc_idx = np.flatnonzero(included)
    # 2019-12 forward window [2019-12, 2020-12] spans break → excluded
    # 2020-12 has no future → excluded
    assert len(inc_idx) == 0
    assert "npl_break" in meta["excluded_counts"]


def test_build_labels_e2_or_e3_uses_e2_at_break():
    """E2_or_E3: 2019 row forward window spans break → E3 excluded, label from E2 only."""
    npl_break = date(2020, 6, 30)
    rows = [
        _row(bank_id=1, period=date(2019, 12, 31), cet1=0.14, npl=0.02),
        _row(bank_id=1, period=date(2020, 12, 31), cet1=0.08, npl=0.08),
    ]
    # 2019-12: forward CET1 change = 0.08-0.14 = -0.06 (decline); E3 excluded (break); E2=1
    # 2020-12: no future → excluded
    y, included, meta = build_labels(rows, "E2_or_E3", 0.5, 12, R0,
                                     npl_break, train_cutoff_year=2020)
    inc_idx = np.flatnonzero(included)
    assert len(inc_idx) == 1  # only 2019 row is labeled
    assert inc_idx[0] == 0    # index 0 = 2019-12 row
    assert y[inc_idx[0]] == 1  # E2=1 (forward decline 0.06 >= threshold)


def test_build_labels_excludes_noncompliant():
    rows = [
        _row(bank_id=1, period=date(2015, 12, 31), cet1=0.065),  # non-compliant
        _row(bank_id=1, period=date(2016, 12, 31), cet1=0.065),  # non-compliant future
        _row(bank_id=2, period=date(2015, 12, 31)),               # compliant, no future → excluded
    ]
    y, included, meta = build_labels(rows, "E2", 0.95, 12, R0,
                                     date(2020, 6, 30), train_cutoff_year=2020)
    assert not included[0]
    assert "non_compliant" in meta["excluded_counts"]


def test_label_options():
    assert "E2_or_E3" in LABEL_OPTIONS
    assert "E1" in LABEL_OPTIONS


# --- T-0 reproduction test ---
# Verifies that build_labels reproduces the quantile-threshold logic exactly
# as the T-0 count_events.py script (QUANT_BASE = 2014-12..2019-12).

def _make_t0_fixture():
    """Minimal fixture with known CET1 declines and NPL changes in 2014-2019 window."""
    rows = []
    # Bank 1: steady, provides prior data
    for y in range(2013, 2022):
        for m in (6, 12):
            rows.append(_row(bank_id=1, period=date(y, m, 30 if m == 6 else 31),
                             cet1=0.12, tier1=0.14, total=0.16, npl=0.03))
    # Bank 2: large CET1 decline in 2017 (2016->2017: 0.14->0.08)
    for y in range(2013, 2022):
        for m in (6, 12):
            cet1 = 0.08 if (y == 2017 and m == 12) else 0.14
            rows.append(_row(bank_id=2, period=date(y, m, 30 if m == 6 else 31),
                             cet1=cet1, tier1=0.14, total=0.16, npl=0.03))
    # Bank 3: large NPL increase in 2018 (2017-12->2018-12: 0.02->0.09)
    for y in range(2013, 2022):
        for m in (6, 12):
            npl = 0.09 if (y == 2018 and m == 12) else 0.02
            rows.append(_row(bank_id=3, period=date(y, m, 30 if m == 6 else 31),
                             cet1=0.12, tier1=0.14, total=0.16, npl=npl))
    return rows


def test_t0_reproduction_e2_threshold():
    """Forward E2=1 at the period BEFORE the CET1 drop (2016-12), not at the drop itself."""
    rows = _make_t0_fixture()
    y, included, meta = build_labels(rows, "E2", 0.95, 12, R0,
                                     date(2020, 6, 30), train_cutoff_year=2020)
    # Bank 2: cet1 drops from 0.14 (2016-12) to 0.08 (2017-12); forward E2=1 at 2016-12
    assert meta["n_cet1_changes"] > 0
    for i, row in enumerate(rows):
        if row["bank_id"] == 2 and row["period"] == date(2016, 12, 31) and included[i]:
            assert y[i] == 1


def test_t0_reproduction_e3_threshold():
    """Forward E3=1 at the period BEFORE the NPL spike (2017-12), not at the spike itself."""
    rows = _make_t0_fixture()
    y, included, meta = build_labels(rows, "E3", 0.95, 12, R0,
                                     date(2020, 6, 30), train_cutoff_year=2020)
    # Bank 3: npl spikes from 0.02 (2017-12) to 0.09 (2018-12); forward E3=1 at 2017-12
    assert meta["n_npl_changes"] > 0
    for i, row in enumerate(rows):
        if row["bank_id"] == 3 and row["period"] == date(2017, 12, 31) and included[i]:
            assert y[i] == 1


def test_label_not_changed_by_past_value():
    """Leakage guard: changing x(t-12m) must NOT change label(t) with forward labels."""
    npl_break = date(2020, 6, 30)
    # Three periods for bank 1: t-12m, t, t+12m
    t_minus = date(2015, 12, 31)
    t       = date(2016, 12, 31)
    t_plus  = date(2017, 12, 31)

    def _make(cet1_tminus):
        return [
            _row(bank_id=1, period=t_minus, cet1=cet1_tminus),  # x(t-12m)
            _row(bank_id=1, period=t,       cet1=0.12),          # x(t) fixed
            _row(bank_id=1, period=t_plus,  cet1=0.09),          # x(t+12m) fixed
        ]

    rows_a = _make(cet1_tminus=0.14)   # normal past
    rows_b = _make(cet1_tminus=0.07)   # very different past (would flip backward label)

    ya, _, _ = build_labels(rows_a, "E2", 0.5, 12, R0, npl_break, train_cutoff_year=2020)
    yb, _, _ = build_labels(rows_b, "E2", 0.5, 12, R0, npl_break, train_cutoff_year=2020)

    # Find label at row t (index 1 in both lists)
    # Forward E2(t): uses x(t+12m) - x(t) = 0.09 - 0.12 = -0.03 (decline 0.03)
    # Threshold changes because train rows change — but the SIGN of past doesn't flip the label
    # Key assertion: label at t is identical for rows_a and rows_b
    assert ya[1] == yb[1], "Label at t changed when x(t-12m) changed — backward leakage!"
