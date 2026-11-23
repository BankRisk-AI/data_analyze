from datetime import date
from pathlib import Path

import pytest
import yaml
from psycopg2.extras import Json

from app.core.rules import evaluate_profile, evaluate_rows, load_profile, validate_profile


def profile(*rules):
    return {
        "profile": "test",
        "rules": [*rules, {
            "id": "composite", "type": "composite_score", "condition": "weighted_sum",
            "severity": "alert_level", "cutoffs": {"green": 0, "amber": 2, "red": 5},
            "source": "test", "status": "verified",
        }],
    }


def rule(rule_id, kind, feature, **extra):
    return {
        "id": rule_id, "type": kind, "feature": feature, "condition": "below",
        "threshold": 0.1, "severity": "amber", "weight": 2,
        "source": "test", "status": "verified", **extra,
    }


def row(bank_id, period, **values):
    return {
        "bank_id": bank_id, "version_id": period.month + period.year * 10,
        "period": period, "flags": {}, **values,
    }


def result(alerts, rule_id):
    return next(x for x in alerts[0]["rule_results"]["rules"] if x["rule_id"] == rule_id)


def test_level_null_is_not_evaluated_and_composite_is_not_evaluated():
    alerts = evaluate_rows(profile(rule("level", "level", "cet1_ratio")), [
        row(1, date(2020, 6, 30), cet1_ratio=None),
    ])
    assert result(alerts, "level")["not_evaluated"] is True
    assert alerts[0]["level"] == "not_evaluated"


def test_trend_crossing_series_break_is_not_evaluated_but_same_definition_is_evaluated():
    p = profile({
        "id": "trend", "type": "trend", "feature": "npl_ratio",
        "condition": "increase_over", "periods": 4, "threshold": 0.01,
        "severity": "amber", "weight": 2, "source": "test", "status": "verified",
    })
    alerts = evaluate_rows(p, [
        row(1, date(2019, 6, 30), npl_ratio=0.02),
        row(1, date(2020, 6, 30), npl_ratio=0.05),
        row(1, date(2021, 6, 30), npl_ratio=0.08),
    ])
    assert result(alerts[1:], "trend")["not_evaluated"] is True
    assert result(alerts[2:], "trend")["triggered"] is True


def test_persistence_relative_specialist_and_composite():
    p = profile(
        rule("persist", "persistence", "roe_annualised", consecutive_periods=2),
        {"id": "relative", "type": "relative", "feature": "npl_ratio",
         "condition": "worst_decile", "percentile": 0.9, "severity": "amber",
         "weight": 2, "source": "test", "status": "verified"},
    )
    rows = [
        row(1, date(2020, 9, 30), roe_annualised=-.1, npl_ratio=.2),
        row(1, date(2020, 12, 31), roe_annualised=-.1, npl_ratio=.2),
        row(1, date(2021, 3, 31), roe_annualised=-.1, npl_ratio=.2),
        row(1, date(2021, 6, 30), roe_annualised=-.1, npl_ratio=.2),
        row(2, date(2021, 6, 30), roe_annualised=.2, npl_ratio=.01,
            flags={"cet1_ratio": ["specialist_institution"]}),
        row(3, date(2021, 6, 30), roe_annualised=.2, npl_ratio=.02),
    ]
    alerts = evaluate_rows(p, rows)
    latest = alerts[3]
    assert result([latest], "persist")["triggered"] is True
    assert result([latest], "relative")["triggered"] is True
    specialist = next(a for a in alerts if a["bank_id"] == 2)
    assert specialist["level"] == "not_evaluated"


def test_persistence_requires_exact_calendar_six_month_observation():
    p = profile(rule("persist", "persistence", "roe_annualised", consecutive_periods=2))
    alerts = evaluate_rows(p, [
        row(1, date(2018, 6, 30), roe_annualised=-.1),
        row(1, date(2018, 9, 30), roe_annualised=-.1),
        row(1, date(2019, 3, 31), roe_annualised=-.1),
        row(1, date(2019, 6, 30), roe_annualised=-.1),
    ])
    assert result([alerts[0]], "persist")["not_evaluated"] is True
    assert result([alerts[1]], "persist")["not_evaluated"] is True
    assert result([alerts[2]], "persist")["triggered"] is True
    assert result([alerts[3]], "persist")["not_evaluated"] is True


def test_npl_persistence_crossing_definition_break_is_not_evaluated():
    p = profile(rule("persist", "persistence", "npl_ratio", condition="above",
                      threshold=.05, consecutive_periods=2))
    alerts = evaluate_rows(p, [
        row(1, date(2019, 12, 31), npl_ratio=.1),
        row(1, date(2020, 6, 30), npl_ratio=.1),
        row(1, date(2020, 12, 31), npl_ratio=.1),
    ])
    assert result([alerts[1]], "persist")["not_evaluated"] is True
    assert result([alerts[1]], "persist")["input_flags"] == ["series_break"]
    assert result([alerts[2]], "persist")["triggered"] is True


def test_profile_validation_rejects_duplicate_ids_and_missing_verified_threshold():
    with pytest.raises(ValueError, match="duplicate"):
        validate_profile(profile(rule("x", "level", "cet1_ratio"),
                                 rule("x", "level", "tier1_ratio")))
    bad = rule("x", "level", "cet1_ratio")
    bad["threshold"] = None
    with pytest.raises(ValueError, match="threshold"):
        validate_profile(profile(bad))


def test_eu_rocet1_thresholds_use_multiplication_factor():
    config = yaml.safe_load(Path("config/rules/eu_eba.yaml").read_text())
    rule = next(r for r in config["rules"] if r["id"] == "rocet1_supervisory_low")
    assert rule["bands"]["amber"]["min"] == pytest.approx(0.06 * 1.2001447434)
    assert rule["bands"]["green"]["above"] == pytest.approx(0.10 * 1.2001447434)


def test_frozen_eu_profile_requires_version_bump_for_changes():
    profile, profile_sha = load_profile("config/rules/eu_eba.yaml")
    assert profile["version"] == "1.1"
    assert profile["frozen"] is True
    assert profile_sha == "28a28fa0f89da8435abdb0d6042a69cb2bff421c456926374dd202e0089f7e40"


def test_persisted_alerts_are_idempotent(db, tmp_path):
    db.cur.execute("INSERT INTO import_batch(status) VALUES ('loaded') RETURNING import_id")
    import_id = db.cur.fetchone()[0]
    db.cur.execute(
        "INSERT INTO bank(lei, name, country_code) VALUES (%s,%s,%s) RETURNING bank_id",
        ("54930000000000000001", "Synthetic Bank", "XX"),
    )
    bank_id = db.cur.fetchone()[0]
    db.cur.execute(
        """INSERT INTO dataset_version(year, quarter, period_end, import_id, version_no, is_active)
           VALUES (2025, 2, '2025-06-30', %s, 1, true) RETURNING version_id""",
        (import_id,),
    )
    version_id = db.cur.fetchone()[0]
    db.cur.execute(
        """INSERT INTO panel_row(version_id, bank_id, cet1_ratio, flags)
           VALUES (%s,%s,%s,%s)""",
        (version_id, bank_id, 0.03, Json({})),
    )
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile(rule("level", "level", "cet1_ratio"))))
    evaluate_profile(db.conn, path)
    evaluate_profile(db.conn, path)
    db.cur.execute("SELECT count(*), count(distinct profile_sha256) FROM alert")
    assert db.cur.fetchone() == (1, 1)


def test_family_max_does_not_sum_correlated_rules():
    p = profile(
        rule("cet1_band", "level", "cet1_ratio", threshold=0.1),
        rule("tier1_band", "level", "tier1_ratio", threshold=0.1),
    )
    alert = evaluate_rows(p, [row(1, date(2025, 6, 30), cet1_ratio=0.05, tier1_ratio=0.05)])[0]
    assert alert["score"] == 1
    assert alert["level"] == "green"
    assert alert["rule_results"]["family_scores"]["capital"]["score"] == 1


def test_family_logic_reasons_and_leverage_cap():
    p = profile(
        rule("cet1_regulatory_min", "level", "cet1_ratio", threshold=0.045),
        {"id": "leverage_supervisory_low", "type": "level", "feature": "leverage_ratio",
         "condition": "band", "bands": {"red": {"below": 0.05}, "amber": {"min": .05, "max": .08}},
         "severity": "amber", "weight": 99, "source": "test", "status": "verified"},
        rule("npl_high", "level", "npl_ratio", condition="above", threshold=0.05),
    )
    alert = evaluate_rows(p, [row(1, date(2025, 6, 30), cet1_ratio=.03, leverage_ratio=.01, npl_ratio=.2)])[0]
    assert alert["level"] == "red"
    assert alert["rule_results"]["level_reason"] == "regulatory_breach:cet1_regulatory_min"
    assert alert["rule_results"]["family_scores"]["capital"]["score"] == 3


def test_two_families_red_and_all_not_evaluated_reason():
    p = profile(
        rule("cet1_drop", "trend", "cet1_ratio", condition="decrease_over", periods=4, threshold=.01),
        rule("npl_high", "persistence", "npl_ratio", condition="above", threshold=.05,
             consecutive_periods=2),
    )
    rows = [
        row(1, date(2024, 6, 30), cet1_ratio=.15, npl_ratio=.10),
        row(1, date(2024, 12, 31), cet1_ratio=.12, npl_ratio=.15),
        row(1, date(2025, 6, 30), cet1_ratio=.10, npl_ratio=.2),
    ]
    alert = evaluate_rows(p, rows)[2]
    assert alert["level"] == "red"
    assert alert["rule_results"]["level_reason"] == "two_families:asset_quality,dynamics"
    empty = evaluate_rows(p, [row(2, date(2025, 6, 30), cet1_ratio=None, npl_ratio=None)])[0]
    assert empty["level"] == "not_evaluated"
    assert empty["rule_results"]["level_reason"] == "all_families_not_evaluated"
