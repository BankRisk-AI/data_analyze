from datetime import date

from app.ml import equal_alert_volume_recall, folds, holm_adjust, lead_time_quarters


def test_temporal_folds_keep_embargo():
    rows = [{"period": date(year, 6, 30), "bank_id": 1} for year in range(2014, 2025)]
    for train, test in folds(rows):
        assert train.size and test.size
        assert max(rows[i]["period"].year for i in train) < min(
            rows[i]["period"].year for i in test) - 1


def test_robustness_feature_policy_excludes_structural_flags():
    from app.ml import FEATURES
    structural = {"stage2_share", "nace_hhi", "leverage_ratio",
                  "loan_growth_qoq", "cet1_ratio", "tier1_ratio",
                  "total_capital_ratio"}
    columns = [f"{feature}_missing" for feature in FEATURES
               if feature not in structural]
    assert "tier1_ratio_missing" not in columns
    assert "stage2_share_missing" not in columns
    assert "roe_annualised_missing" in columns


def test_equal_alert_volume_recall_uses_period_k():
    assert equal_alert_volume_recall(
        ["a", "a", "b", "b"], [1, 0, 0, 1], [.9, .8, .1, .9],
        [True, False, False, True]) == 1.0


def test_holm_adjustment():
    assert holm_adjust([.01, .04, .03]) == [.03, .06, .06]


def test_lead_time_and_censoring():
    result = lead_time_quarters(date(2020, 6, 30),
                                 [date(2019, 6, 30), date(2019, 12, 31),
                                  date(2020, 6, 30)],
                                 [date(2019, 12, 31)], [date(2019, 6, 30)])
    assert result["lead_quarters"] == -2
    assert result["censored"] is True
