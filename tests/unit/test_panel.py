from datetime import date

import pytest

from app.core.panel import (
    _outliers, annualise_profit, crosses_series_break, growth_rate, hhi,
    is_quarter_pair,
)


def test_annualise_profit_uses_reported_quarters():
    assert annualise_profit(100, 2, 6, "2024-06-30") == (200.0, False)


def test_annualise_profit_assumes_calendar_when_metadata_missing():
    assert annualise_profit(100, None, 12, None) == (100.0, True)


def test_hhi_ignores_zero_values_and_returns_concentration():
    assert hhi([50.0, 50.0, 0.0]) == 0.5
    assert hhi([0.0, 0.0]) is None


def test_outliers_support_configurable_k_and_positive_log_transform():
    rows = [{"value": float(i), "_flags": {"value": []}} for i in range(1, 21)]
    rows[-1]["value"] = 100.0
    _outliers(rows, "value", k=3, transform="raw")
    assert "outlier" in rows[-1]["_flags"]["value"]
    rows = [{"value": float(i), "_flags": {"value": []}} for i in range(1, 21)]
    rows[-1]["value"] = 100.0
    _outliers(rows, "value", k=5, transform="log")
    assert "outlier" not in rows[-1]["_flags"]["value"]


def test_growth_does_not_treat_frequency_boundary_as_qoq():
    assert not is_quarter_pair(date(2018, 9, 30), date(2018, 6, 30), "semi_annual")
    assert is_quarter_pair(date(2018, 12, 31), date(2018, 9, 30), "quarterly")
    assert growth_rate(130, 100) == pytest.approx(0.3)
    assert growth_rate(160, 100) == pytest.approx(0.6)
    assert growth_rate(160, 100) != growth_rate(130, 100)


def test_permanent_series_break_only_nulls_cross_definition_growth():
    break_period = date(2020, 6, 30)
    periods = [date(2020, 3, 31), date(2020, 6, 30),
               date(2020, 9, 30), date(2021, 6, 30)]
    assert [crosses_series_break(periods[i], periods[i - 1], break_period)
            for i in range(1, len(periods))] == [True, False, False]
