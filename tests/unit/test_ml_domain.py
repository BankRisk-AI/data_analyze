"""Unit tests for domain pure functions moved/added in ML-R-A refactor.

Tests capture CURRENT behaviour (including current bugs); those marked
'R-B will change' document known bugs to be fixed in ML-R-B.
"""
from __future__ import annotations

import numpy as np
import pytest
from datetime import date


# ---------------------------------------------------------------------------
# domain/thresholds.py
# ---------------------------------------------------------------------------
from app.modules.eba_ml.domain.thresholds import (
    matched_far_threshold, max_ur_threshold, compute_thresholds)


def test_matched_far_threshold_basic():
    scores = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    # alert_share=0.4 -> quantile at 0.6 -> 0.3 (index 2 of 5)
    result = matched_far_threshold(scores, 0.4)
    assert abs(result - np.quantile(scores, 0.6)) < 1e-10


def test_matched_far_threshold_clamps_at_zero():
    scores = np.array([0.1, 0.5, 0.9])
    # alert_share > 1.0 would give negative quantile; clamp to 0 -> min score
    result = matched_far_threshold(scores, 1.5)
    assert result == float(np.quantile(scores, 0.0))


def test_max_ur_threshold_default_p90():
    scores = np.linspace(0, 1, 101)
    assert abs(max_ur_threshold(scores) - 0.9) < 1e-6


def test_compute_thresholds_returns_both():
    scores = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    result = compute_thresholds(scores, 0.3)
    assert "matched_far" in result
    assert "max_ur_0_9" in result
    assert result["max_ur_0_9"] == float(np.quantile(scores, 0.9))


# ---------------------------------------------------------------------------
# domain/families.py
# ---------------------------------------------------------------------------
from app.modules.eba_ml.domain.families import (
    assign_family, group_shap_values, FAMILIES, SENSITIVITY_GROUPS)


def test_assign_family_capital():
    assert assign_family("cet1_ratio") == "Capital"


def test_assign_family_earnings():
    assert assign_family("roe_annualised") == "Earnings"


def test_assign_family_default_liquidity():
    assert assign_family("unknown_feature") == "Liquidity"


def test_assign_family_growth():
    assert assign_family("loan_growth_yoy") == "Growth"


def test_families_disjoint():
    all_members = [m for s in FAMILIES.values() for m in s]
    assert len(all_members) == len(set(all_members)), "feature appears in two families"


def test_sensitivity_groups_cover_primary_families():
    primary_names = set(FAMILIES.keys())
    grouped = {f for sub in SENSITIVITY_GROUPS.values() for f in sub}
    assert primary_names == grouped, "SENSITIVITY_GROUPS must cover all primary families"


def test_group_shap_values_sums_correctly():
    shap_vals = np.array([[1.0, 2.0, 3.0]])
    columns = ["cet1_ratio", "roe_annualised", "cet1_ratio_rank"]
    grouped = group_shap_values(shap_vals, columns)
    # cet1_ratio and cet1_ratio_rank -> Capital; roe_annualised -> Earnings
    assert abs(grouped["Capital"][0] - 4.0) < 1e-10  # 1.0 + 3.0
    assert abs(grouped["Earnings"][0] - 2.0) < 1e-10


def test_group_shap_values_change12m_stripped():
    shap_vals = np.array([[5.0]])
    columns = ["npl_ratio_change12m"]
    grouped = group_shap_values(shap_vals, columns)
    # npl_ratio -> Asset quality
    assert "Asset quality" in grouped
    assert abs(grouped["Asset quality"][0] - 5.0) < 1e-10


# ---------------------------------------------------------------------------
# domain/metrics.py — existing functions, regression tests
# ---------------------------------------------------------------------------
from app.modules.eba_ml.domain.metrics import (
    _classification_metrics, _cluster_bootstrap, _hyp_bootstrap,
    _hyp_wilcoxon, holm_adjust, equal_alert_volume_recall, lead_time_quarters)


def test_classification_metrics_perfect():
    actual = np.array([1, 0, 1, 0])
    scores = np.array([0.9, 0.1, 0.8, 0.2])
    result = _classification_metrics(actual, scores)
    assert result["pr_auc"] == 1.0
    assert result["roc_auc"] == 1.0


def test_classification_metrics_no_positives_roc_none():
    actual = np.array([0, 0, 0])
    scores = np.array([0.1, 0.5, 0.9])
    result = _classification_metrics(actual, scores)
    assert result["roc_auc"] is None


def test_cluster_bootstrap_returns_two_floats():
    rng = np.random.default_rng(42)
    n = 50
    actual = rng.integers(0, 2, n)
    cand = rng.random(n)
    ref = rng.random(n)
    banks = rng.integers(0, 5, n).astype(str)
    ci = _cluster_bootstrap(actual, cand, ref, banks, seed=1, n=100)
    assert len(ci) == 2
    assert ci[0] <= ci[1]


def test_hyp_bootstrap_estimate_matches_direct():
    from sklearn.metrics import average_precision_score
    rng = np.random.default_rng(99)
    y = rng.integers(0, 2, 40)
    cand = rng.random(40)
    ref = rng.random(40)
    banks = np.array(["a"] * 20 + ["b"] * 20)
    result = _hyp_bootstrap(y, cand, ref, banks, "pr", seed=0, n=100)
    expected = average_precision_score(y, cand) - average_precision_score(y, ref)
    assert abs(result["estimate"] - expected) < 1e-10


def test_hyp_wilcoxon_too_few_returns_exploratory():
    result = _hyp_wilcoxon([1.0, 2.0])
    assert result["status"] == "exploratory"


def test_hyp_wilcoxon_sufficient_data():
    result = _hyp_wilcoxon([1.0, 2.0, 3.0, 4.0, 5.0])
    assert result["status"] == "exact"
    assert 0 <= result["p"] <= 1


def test_holm_adjust_known_values():
    assert holm_adjust([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]


def test_equal_alert_volume_recall_full():
    assert equal_alert_volume_recall(
        ["a", "a", "b", "b"], [1, 0, 0, 1], [0.9, 0.8, 0.1, 0.9],
        [True, False, False, True]) == 1.0


def test_lead_time_quarters_censored():
    result = lead_time_quarters(
        date(2020, 6, 30),
        [date(2019, 6, 30), date(2019, 12, 31), date(2020, 6, 30)],
        [date(2019, 12, 31)], [date(2019, 6, 30)])
    assert result["lead_quarters"] == -2
    assert result["censored"] is True


def test_lead_time_quarters_no_ml_alert():
    result = lead_time_quarters(
        date(2020, 6, 30),
        [date(2019, 6, 30)],
        [], [date(2019, 6, 30)])
    assert result["lead_quarters"] is None


# ---------------------------------------------------------------------------
# domain/lead_time.py — re-export check
# ---------------------------------------------------------------------------
from app.modules.eba_ml.domain.lead_time import lead_time_quarters as lt_via_lead_time


def test_lead_time_reexport_is_same_function():
    assert lt_via_lead_time is lead_time_quarters
