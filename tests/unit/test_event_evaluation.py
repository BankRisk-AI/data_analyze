from datetime import date

import yaml
import pytest

from app.event_evaluation import evaluate_events, relative_usefulness, usefulness_metrics


def test_sarlin_relative_usefulness_hand_calculation():
    # 2 TP, 1 FN, 1 FP, 6 TN: P1=.3, T1=1/3, T2=1/7.
    metrics = usefulness_metrics(2, 1, 1, 6)
    assert metrics["p1"] == 0.3
    expected = (min(0.7 * 0.3, 0.3 * 0.7)
                - (0.7 * (1 / 3) * 0.3 + 0.3 * (1 / 7) * 0.7)) / 0.21
    assert relative_usefulness(2, 1, 1, 6, 0.7) == pytest.approx(expected)
    assert metrics["mu_star"] == 0.5


class _Cursor:
    def __init__(self):
        self.rows = []

    def execute(self, query, params=()):
        if "SELECT bank_id,trim(lei)" in query:
            self.rows = [(1, "TESTBANK000000000001")]
        elif "FROM panel_row" in query:
            self.rows = [(1, date(2021, 6, 30), {})]
        elif "FROM alert" in query:
            self.rows = [(1, date(2021, 6, 30), "red",
                          {"level_reason": "synthetic", "family_scores": {}})]

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Connection:
    def cursor(self):
        return _Cursor()


def test_synthetic_event_hit_lead_time_and_eligibility(tmp_path):
    events = tmp_path / "events.yaml"
    events.write_text(yaml.safe_dump({"events": [{
        "event_id": "synthetic",
        "bank_lei": "TESTBANK000000000001",
        "bank_name": "Synthetic",
        "event_date": "2022-01-01",
        "event_type": "foltf",
        "cause": "fundamental",
        "set": "primary",
        "status": "included",
    }]}))
    result = evaluate_events(_Connection(), "config/rules/eu_eba.yaml", events)
    assert result["evaluable_events"] == 1
    assert result["metrics"]["red"]["hit_rate_percent"] == 100
    assert result["metrics"]["red"]["lead_time_months"]["median"] == 7
    assert result["events"][0]["observations"][0]["level"] == "red"
