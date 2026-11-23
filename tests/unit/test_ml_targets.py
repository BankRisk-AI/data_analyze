"""Unit tests for _target_rows() — T1-T5 labelling logic.

All tests use the pure function signature _target_rows(rows, event_ids, events, event_start_months).
No DB or file I/O.
"""
from datetime import date

import pytest

from app.modules.eba_ml.application.dataset import _target_rows


def _row(bank_id, period, cet1=None, roe=None, npl=None):
    return {
        "bank_id": bank_id,
        "period": period,
        "cet1_ratio": cet1,
        "tier1_ratio": None,
        "total_capital_ratio": None,
        "leverage_ratio": None,
        "npl_ratio": npl,
        "stage2_share": None,
        "roe_annualised": roe,
        "nace_hhi": None,
        "sovereign_hhi": None,
        "loan_growth_qoq": None,
        "loan_growth_yoy": None,
    }


def _run(rows, event_ids=None, events=None, event_start_months=3):
    return _target_rows(rows, event_ids or {}, events or [], event_start_months)


# ─── T2: CET1 drops below 0.11 within 12 months ─────────────────────────────

def test_t2_positive_when_cet1_drops_below_threshold():
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.14),
        _row(1, date(2020, 12, 31), cet1=0.09),
    ]
    result = _run(rows)
    assert (1, date(2020, 6, 30)) in result["T2"]
    assert (1, date(2020, 12, 31)) not in result["T2"]


def test_t2_negative_when_cet1_stays_above_threshold():
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.14),
        _row(1, date(2020, 12, 31), cet1=0.12),
    ]
    assert (1, date(2020, 6, 30)) not in _run(rows)["T2"]


def test_t2_negative_when_cet1_already_below_threshold():
    # T2 requires current cet1 >= 0.11; if already below, T2 is False
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.09),
        _row(1, date(2020, 12, 31), cet1=0.07),
    ]
    assert (1, date(2020, 6, 30)) not in _run(rows)["T2"]


def test_t2_negative_when_no_future_rows():
    rows = [_row(1, date(2020, 6, 30), cet1=0.14)]
    assert (1, date(2020, 6, 30)) not in _run(rows)["T2"]


def test_t2_respects_12_month_window():
    # Future row at exactly +12m: included
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.14),
        _row(1, date(2021, 6, 30), cet1=0.09),  # exactly +12m
    ]
    assert (1, date(2020, 6, 30)) in _run(rows)["T2"]

    # Future row at +12m+1day (outside window — but rows are monthly so this tests +18m)
    rows2 = [
        _row(1, date(2020, 6, 30), cet1=0.14),
        _row(1, date(2021, 12, 31), cet1=0.09),  # +18m, outside 12m window
    ]
    assert (1, date(2020, 6, 30)) not in _run(rows2)["T2"]


# ─── T3: CET1 drops by >= 0.03 within 12 months ─────────────────────────────

def test_t3_positive_when_cet1_drops_at_least_3pct():
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.12),
        _row(1, date(2020, 12, 31), cet1=0.09),  # drop of 0.03
    ]
    assert (1, date(2020, 6, 30)) in _run(rows)["T3"]


def test_t3_negative_when_drop_less_than_3pct():
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.12),
        _row(1, date(2020, 12, 31), cet1=0.10),  # drop of 0.02
    ]
    assert (1, date(2020, 6, 30)) not in _run(rows)["T3"]


def test_t3_works_even_when_cet1_below_0_11():
    # T3 has no floor on current cet1 (unlike T2)
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.08),
        _row(1, date(2020, 12, 31), cet1=0.04),  # drop of 0.04
    ]
    assert (1, date(2020, 6, 30)) in _run(rows)["T3"]


def test_t3_negative_when_cet1_is_none():
    rows = [
        _row(1, date(2020, 6, 30), cet1=None),
        _row(1, date(2020, 12, 31), cet1=0.04),
    ]
    assert (1, date(2020, 6, 30)) not in _run(rows)["T3"]


# ─── T4: future distress, not currently distressed ───────────────────────────

def test_t4_positive_when_future_distress_but_not_current():
    rows = [
        _row(1, date(2020, 6, 30), roe=0.05, npl=0.03),   # currently healthy
        _row(1, date(2020, 12, 31), roe=-0.01, npl=0.10),  # future distress
    ]
    assert (1, date(2020, 6, 30)) in _run(rows)["T4"]


def test_t4_negative_when_already_distressed():
    rows = [
        _row(1, date(2020, 6, 30), roe=-0.02, npl=0.10),   # already distressed
        _row(1, date(2020, 12, 31), roe=-0.05, npl=0.12),  # still distressed
    ]
    assert (1, date(2020, 6, 30)) not in _run(rows)["T4"]


def test_t4_negative_when_no_future_distress():
    rows = [
        _row(1, date(2020, 6, 30), roe=0.05, npl=0.03),
        _row(1, date(2020, 12, 31), roe=0.02, npl=0.05),
    ]
    assert (1, date(2020, 6, 30)) not in _run(rows)["T4"]


def test_t4_exclusion_requires_both_roe_and_npl_non_none():
    # If current row has npl=None, exclusion check is False → T4 fires if future is distressed
    rows = [
        _row(1, date(2020, 6, 30), roe=-0.01, npl=None),   # partial None — exclusion doesn't fire
        _row(1, date(2020, 12, 31), roe=-0.02, npl=0.10),
    ]
    assert (1, date(2020, 6, 30)) in _run(rows)["T4"]


def test_t4_negative_only_roe_condition_met_in_future():
    # Both roe AND npl must be non-None AND conditions met in future
    rows = [
        _row(1, date(2020, 6, 30), roe=0.05, npl=0.03),
        _row(1, date(2020, 12, 31), roe=-0.01, npl=0.05),  # ROE < 0 but NPL not > 0.08
    ]
    assert (1, date(2020, 6, 30)) not in _run(rows)["T4"]


# ─── T1: external event in window ────────────────────────────────────────────

def test_t1_positive_when_event_in_window():
    event_ids = {"LEI001": {1}}
    events = [{"bank_lei": "LEI001", "event_date": "2020-09-30",
               "set": "primary", "status": "included"}]
    rows = [_row(1, date(2020, 6, 30))]
    # period=2020-06-30, event_start=3m → 2020-09-30, end → 2021-06-30
    result = _target_rows(rows, event_ids, events, event_start_months=3)
    assert (1, date(2020, 6, 30)) in result["T1"]


def test_t1_negative_when_event_before_window():
    event_ids = {"LEI001": {1}}
    events = [{"bank_lei": "LEI001", "event_date": "2020-08-30",
               "set": "primary", "status": "included"}]
    rows = [_row(1, date(2020, 6, 30))]
    # event_start_months=3 → window starts 2020-09-30; event at 2020-08-30 is before window
    result = _target_rows(rows, event_ids, events, event_start_months=3)
    assert (1, date(2020, 6, 30)) not in result["T1"]


def test_t1_negative_when_event_after_12m():
    event_ids = {"LEI001": {1}}
    events = [{"bank_lei": "LEI001", "event_date": "2021-07-01",
               "set": "primary", "status": "included"}]
    rows = [_row(1, date(2020, 6, 30))]
    result = _target_rows(rows, event_ids, events, event_start_months=3)
    assert (1, date(2020, 6, 30)) not in result["T1"]


def test_t1_negative_when_bank_not_in_event_ids():
    event_ids = {"LEI999": {99}}
    events = [{"bank_lei": "LEI001", "event_date": "2020-09-30",
               "set": "primary", "status": "included"}]
    rows = [_row(1, date(2020, 6, 30))]
    result = _target_rows(rows, event_ids, events, event_start_months=3)
    assert (1, date(2020, 6, 30)) not in result["T1"]


# ─── T5 and T5_noT1 composition ──────────────────────────────────────────────

def test_t5_is_union_of_t1_to_t4():
    # T2 fires: should trigger T5
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.14),
        _row(1, date(2020, 12, 31), cet1=0.09),
    ]
    result = _run(rows)
    assert (1, date(2020, 6, 30)) in result["T5"]


def test_t5_no_t1_excludes_pure_t1():
    # Only T1 fires, not T2/T3/T4 → T5=True, T5_noT1=False
    event_ids = {"LEI001": {1}}
    events = [{"bank_lei": "LEI001", "event_date": "2020-09-30"}]
    rows = [_row(1, date(2020, 6, 30))]
    result = _target_rows(rows, event_ids, events, event_start_months=3)
    assert (1, date(2020, 6, 30)) in result["T5"]
    assert (1, date(2020, 6, 30)) not in result["T5_noT1"]


def test_t5_no_t1_includes_t2():
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.14),
        _row(1, date(2020, 12, 31), cet1=0.09),
    ]
    result = _run(rows)
    assert (1, date(2020, 6, 30)) in result["T5_noT1"]


# ─── Multiple banks independence ─────────────────────────────────────────────

def test_banks_are_independent():
    rows = [
        _row(1, date(2020, 6, 30), cet1=0.14),
        _row(1, date(2020, 12, 31), cet1=0.09),  # bank 1: T2 fires
        _row(2, date(2020, 6, 30), cet1=0.14),
        _row(2, date(2020, 12, 31), cet1=0.12),  # bank 2: T2 does NOT fire
    ]
    result = _run(rows)
    assert (1, date(2020, 6, 30)) in result["T2"]
    assert (2, date(2020, 6, 30)) not in result["T2"]


# ─── Empty inputs ────────────────────────────────────────────────────────────

def test_empty_rows_returns_empty_sets():
    result = _run([])
    assert all(len(v) == 0 for v in result.values())
    assert set(result.keys()) == {"T1", "T2", "T3", "T4", "T5", "T5_noT1"}
