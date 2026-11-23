"""Event-window evaluation shared by the rules and future ML evaluators."""
from __future__ import annotations

import math
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.core.rules import load_profile


def _months_before(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    return date(year, month, monthrange(year, month)[1])


def _months_after(value: date, months: int) -> date:
    return _months_before(value, -months)


def _wilson(hits: int, total: int) -> tuple[float | None, float | None]:
    if not total:
        return None, None
    p = hits / total
    z = 1.959963984540054
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return 100 * (centre - spread), 100 * (centre + spread)


def _level_hit(level: str, threshold: str) -> bool:
    return level == "red" if threshold == "red" else level in {"amber", "red"}


def relative_usefulness(tp: int, fn: int, fp: int, tn: int, mu: float) -> float:
    """Sarlin (2013) relative usefulness from observation-level outcomes."""
    event_total = tp + fn
    nonevent_total = fp + tn
    if not event_total or not nonevent_total:
        return 0.0
    t1 = fn / event_total
    t2 = fp / nonevent_total
    p1 = event_total / (event_total + nonevent_total)
    p2 = 1.0 - p1
    benchmark = min(mu * p1, (1.0 - mu) * p2)
    loss = mu * t1 * p1 + (1.0 - mu) * t2 * p2
    return (benchmark - loss) / benchmark if benchmark else 0.0


def usefulness_metrics(tp: int, fn: int, fp: int, tn: int) -> dict[str, Any]:
    event_total = tp + fn
    nonevent_total = fp + tn
    total = event_total + nonevent_total
    p1 = event_total / total if total else 0.0
    values = {str(mu): relative_usefulness(tp, fn, fp, tn, mu)
              for mu in (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)}
    positive = [mu for mu in (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)
               if values[str(mu)] > 0]
    return {"p1": p1, "usefulness": values, "mu_star": min(positive) if positive else None}


def _observation_metrics(alerts: dict[tuple[int, date], str],
                        event_keys: set[tuple[int, date]],
                        evaluated_keys: set[tuple[int, date]],
                        threshold: str = "red") -> dict[str, Any]:
    event_keys &= evaluated_keys
    tp = sum(_level_hit(alerts.get(key, "not_evaluated"), threshold) for key in event_keys)
    fn = len(event_keys) - tp
    nonevent = evaluated_keys - event_keys
    fp = sum(_level_hit(alerts.get(key, "not_evaluated"), threshold) for key in nonevent)
    tn = len(nonevent) - fp
    result = usefulness_metrics(tp, fn, fp, tn)
    result.update({"tp": tp, "fn": fn, "fp": fp, "tn": tn,
                  "hit_rate": tp / (tp + fn) if tp + fn else 0.0,
                  "false_alarm_rate": fp / (fp + tn) if fp + tn else 0.0,
                  "noise_to_signal": (fp / (fp + tn)) / (tp / (tp + fn))
                  if tp and fp + tn else None})
    return result


def evaluate_baselines(conn, profile_path: str | Path, events_path: str | Path,
                       set_name: str = "primary",
                       profile_sha_override: str | None = None) -> dict[str, Any]:
    """Evaluate fixed dashboard baselines using the same event windows."""
    catalogue = yaml.safe_load(Path(events_path).read_text(encoding="utf-8")) or {}
    events = [e for e in catalogue.get("events", [])
              if e.get("status") == "included" and (set_name == "all" or e.get("set") == set_name)]
    with conn.cursor() as cur:
        cur.execute("SELECT bank_id,trim(lei) FROM bank")
        bank_leis = {lei: bank_id for bank_id, lei in cur.fetchall()}
        cur.execute("""SELECT p.bank_id,v.period_end,p.cet1_ratio,p.npl_ratio,p.roe_annualised,
                              p.leverage_ratio,p.flags
                       FROM panel_row p JOIN dataset_version v USING(version_id)
                       WHERE v.is_active ORDER BY v.period_end""")
        panel = cur.fetchall()
        profile, sha = load_profile(profile_path)
        sha = profile_sha_override or sha
        cur.execute("""SELECT bank_id,v.period_end,level FROM alert
                       JOIN dataset_version v USING(version_id)
                       WHERE profile_sha256=%s""", (sha,))
        profile_alerts = cur.fetchall()
    panel_by_bank: dict[int, list[tuple[date, dict[str, Any]]]] = {}
    for bank_id, period, cet1, npl, roe, leverage, flags in panel:
        panel_by_bank.setdefault(bank_id, []).append(
            (period, {"cet1_ratio": cet1, "npl_ratio": npl, "roe_annualised": roe,
                      "leverage_ratio": leverage, "flags": flags or {}}))
    alert_by_key = {(bank_id, period): level for bank_id, period, level in profile_alerts}
    event_ids = {str(e["bank_lei"]).strip(): {bank_leis[str(e["bank_lei"]).strip()]}
                 for e in events if str(e["bank_lei"]).strip() in bank_leis}
    evaluated_keys = {
        (bank_id, period)
        for bank_id, rows in panel_by_bank.items()
        for period, values in rows
        if not any("specialist_institution" in v for v in values["flags"].values())
        and alert_by_key.get((bank_id, period), "not_evaluated") != "not_evaluated"
    }
    event_keys: set[tuple[int, date]] = set()
    for event in events:
        ids = event_ids.get(str(event["bank_lei"]).strip(), set())
        event_date = date.fromisoformat(str(event["event_date"]))
        event_keys.update(
            (bank_id, period)
            for bank_id in ids
            for period, _ in panel_by_bank.get(bank_id, [])
            if _months_before(event_date, 12) <= period <= _months_before(event_date, 3)
        )
    event_windows = {bank_id: [(date.fromisoformat(str(e["event_date"])), e)
                               for e in events if bank_id in event_ids.get(str(e["bank_lei"]).strip(), set())]
                     for bank_id in panel_by_bank}

    def metric(alerts: dict[tuple[int, date], str]) -> dict[str, Any]:
        eligible = []
        for event in events:
            ids = event_ids.get(str(event["bank_lei"]).strip(), set())
            event_date = date.fromisoformat(str(event["event_date"]))
            obs = [(bank_id, period) for bank_id in ids for period, _ in panel_by_bank.get(bank_id, [])
                   if _months_before(event_date, 12) <= period <= _months_before(event_date, 3)]
            if obs:
                eligible.append(any(alerts.get(key) == "red" for key in obs))
        hits = sum(eligible)
        non_event = total_non_event = false = all_alert = 0
        for bank_id, rows in panel_by_bank.items():
            for period, values in rows:
                specialist = any("specialist_institution" in v for v in values["flags"].values())
                if specialist:
                    continue
                future = any(period < event_date <= _months_after(period, 12)
                             for event_date, _ in event_windows.get(bank_id, []))
                is_red = alerts.get((bank_id, period)) == "red"
                all_alert += is_red
                if not future:
                    total_non_event += 1
                    false += is_red
                if future and is_red:
                    non_event += 1
        hit_rate = hits / len(eligible) if eligible else 0.0
        far = false / total_non_event if total_non_event else 0.0
        precision = non_event / all_alert if all_alert else 0.0
        alert_share = all_alert / sum(len(v) for v in panel_by_bank.values())
        low, high = _wilson(hits, len(eligible))
        sarlin = _observation_metrics(alerts, event_keys, evaluated_keys)
        return {"hit_rate": hit_rate, "wilson": [low, high], "false_alarm_rate": far,
                "precision": precision, "alert_share": alert_share,
                "noise_to_signal": far / hit_rate if hit_rate else None,
                **{key: sarlin[key] for key in
                   ("p1", "usefulness", "mu_star", "tp", "fn", "fp", "tn")},
                "sarlin": sarlin}

    baseline_maps: dict[str, dict[tuple[int, date], str]] = {}
    for key in ("B1 NPL > 8%", "B2 CET1 < 11%", "B3 RoCET1 < 0",
                "B4 NPL > 8% or CET1 < 11%", "B5 regulatory minima",
                "B6 naive persistence"):
        baseline_maps[key] = {}
    first_red_banks = {bank_id for bank_id, rows in panel_by_bank.items()
                       if rows and alert_by_key.get((bank_id, rows[0][0])) == "red"}
    for bank_id, rows in panel_by_bank.items():
        for period, values in rows:
            npl, cet1, roe, leverage = (values[k] for k in ("npl_ratio", "cet1_ratio", "roe_annualised", "leverage_ratio"))
            minimum = ((cet1 is not None and cet1 < .045) or
                       (leverage is not None and leverage < .03) or
                       (cet1 is not None and cet1 < .07))
            checks = {
                "B1 NPL > 8%": npl is not None and npl > .08,
                "B2 CET1 < 11%": cet1 is not None and cet1 < .11,
                "B3 RoCET1 < 0": roe is not None and roe < 0,
                "B4 NPL > 8% or CET1 < 11%": (npl is not None and npl > .08) or (cet1 is not None and cet1 < .11),
                "B5 regulatory minima": minimum,
                "B6 naive persistence": bank_id in first_red_banks,
            }
            for name, value in checks.items():
                if value:
                    baseline_maps[name][(bank_id, period)] = "red"
    # Analytical random baseline: period red shares imply the same expected event hit.
    random_metric = metric(baseline_maps["B1 NPL > 8%"])
    period_shares: dict[date, float] = {}
    for period in {period for rows in panel_by_bank.values() for period, _ in rows}:
        eligible = [(bank_id, period) for bank_id, rows in panel_by_bank.items()
                    if any(p == period for p, _ in rows)]
        period_shares[period] = (
            sum(alert_by_key.get(key) == "red" for key in eligible) / len(eligible)
            if eligible else 0.0
        )
    expected_hits = []
    for event in events:
        event_date = date.fromisoformat(str(event["event_date"]))
        window = [period for rows in panel_by_bank.values() for period, _ in rows
                  if _months_before(event_date, 12) <= period <= _months_before(event_date, 3)]
        expected_hits.append(sum(period_shares.get(period, 0) for period in set(window)) / len(set(window))
                             if window else 0.0)
    random_metric["hit_rate"] = sum(expected_hits) / len(expected_hits) if expected_hits else 0.0
    random_metric["false_alarm_rate"] = sum(period_shares.values()) / len(period_shares) if period_shares else 0.0
    random_metric["precision"] = random_metric["hit_rate"]
    random_metric["alert_share"] = random_metric["false_alarm_rate"]
    random_metric.update(usefulness_metrics(
        random_metric["hit_rate"] * len(event_keys),
        (1 - random_metric["hit_rate"]) * len(event_keys),
        random_metric["false_alarm_rate"] * (len(evaluated_keys) - len(event_keys)),
        (1 - random_metric["false_alarm_rate"]) * (len(evaluated_keys) - len(event_keys)),
    ))
    baseline_maps["B7 random baseline"] = {}
    results = {name: metric(values) for name, values in baseline_maps.items()}
    for name, threshold in (("v1.1 red", "red"), ("v1.1 amber_or_red", "amber")):
        results[name] = _observation_metrics(alert_by_key, event_keys, evaluated_keys, threshold)
    return {"set": set_name, "baselines": results, "random": random_metric}


def evaluate_events(conn, profile_path: str | Path, events_path: str | Path,
                    set_name: str = "primary", profile_sha_override: str | None = None) -> dict[str, Any]:
    profile, profile_sha = load_profile(profile_path)
    profile_sha = profile_sha_override or profile_sha
    catalogue = yaml.safe_load(Path(events_path).read_text(encoding="utf-8")) or {}
    events = [
        event for event in catalogue.get("events", [])
        if event.get("status") == "included"
        and (set_name == "all" or event.get("set") == set_name)
    ]
    crosswalk = yaml.safe_load(Path("config/bank_crosswalk.yaml").read_text(encoding="utf-8")) or {}
    groups: dict[str, set[str]] = {}
    for item in crosswalk.get("crosswalks", []):
        if item.get("status") == "approved":
            groups[item["group_id"]] = {str(m["lei"]).strip() for m in item.get("members", [])}

    with conn.cursor() as cur:
        cur.execute("SELECT bank_id,trim(lei) FROM bank")
        bank_leis = {lei: bank_id for bank_id, lei in cur.fetchall()}
        lei_to_ids: dict[str, set[int]] = {}
        for lei, bank_id in bank_leis.items():
            lei_to_ids[lei] = {bank_id}
        for leis in groups.values():
            ids = {bank_leis[lei] for lei in leis if lei in bank_leis}
            for lei in leis:
                lei_to_ids.setdefault(lei, set()).update(ids)
        cur.execute("""SELECT p.bank_id,v.period_end,p.flags
                       FROM panel_row p JOIN dataset_version v USING(version_id)
                       WHERE v.is_active ORDER BY v.period_end""")
        panel = cur.fetchall()
        cur.execute("""SELECT a.bank_id,v.period_end,a.level,a.rule_results
                       FROM alert a JOIN dataset_version v USING(version_id)
                       WHERE a.profile_sha256=%s ORDER BY v.period_end""", (profile_sha,))
        alerts = cur.fetchall()

    panel_by_bank: dict[int, list[tuple[date, dict]]] = {}
    for bank_id, period, flags in panel:
        panel_by_bank.setdefault(bank_id, []).append((period, flags or {}))
    alert_by_key: dict[tuple[int, date], dict] = {
        (bank_id, period): {"level": level, "rule_results": results or {}}
        for bank_id, period, level, results in alerts
    }
    event_rows = []
    evaluable = []
    for event in events:
        event_date = date.fromisoformat(str(event["event_date"]))
        ids = lei_to_ids.get(str(event["bank_lei"]).strip(), set())
        observations = []
        for bank_id in ids:
            for period, _flags in panel_by_bank.get(bank_id, []):
                if _months_before(event_date, 12) <= period <= _months_before(event_date, 3):
                    alert = alert_by_key.get((bank_id, period))
                    if alert:
                        observations.append({
                            "period": period.isoformat(), "level": alert["level"],
                            "reason": alert["rule_results"].get("level_reason"),
                            "family_scores": alert["rule_results"].get("family_scores", {}),
                        })
        eligible = bool(observations)
        if eligible:
            evaluable.append(event)
        event_rows.append({**event, "eligible": eligible, "observations": sorted(observations, key=lambda x: x["period"])})

    thresholds = ("red", "amber_or_red")
    metrics = {}
    event_windows = {
        bank_id: [
            (date.fromisoformat(str(event["event_date"])), event)
            for event in events
            if bank_id in lei_to_ids.get(str(event["bank_lei"]).strip(), set())
        ]
        for bank_id in panel_by_bank
    }
    for threshold in thresholds:
        hits = []
        for event in event_rows:
            if event["eligible"]:
                hits.append(any(_level_hit(row["level"], threshold) for row in event["observations"]))
        hit_count = sum(hits)
        low, high = _wilson(hit_count, len(hits))
        lead = []
        for event, hit in zip((e for e in event_rows if e["eligible"]), hits):
            if hit:
                first = next(row for row in event["observations"] if _level_hit(row["level"], threshold))
                first_date = date.fromisoformat(first["period"])
                lead.append((event["event_date"], first_date))
        lead_months = [
            (date.fromisoformat(str(event_date)).year - first.year) * 12
            + date.fromisoformat(str(event_date)).month - first.month
            for event_date, first in lead
        ]
        metrics[threshold] = {
            "hit_rate_percent": 100 * hit_count / len(hits) if hits else None,
            "wilson_95_percent": [low, high],
            "lead_time_months": {
                "median": sorted(lead_months)[len(lead_months) // 2] if lead_months else None,
                "min": min(lead_months) if lead_months else None,
                "max": max(lead_months) if lead_months else None,
            },
            "evaluable_events": len(hits),
        }
        event_alerts = 0
        all_alerts = 0
        false_alerts = 0
        eligible_non_event_periods = 0
        for bank_id, rows in panel_by_bank.items():
            for period, flags in rows:
                specialist = any("specialist_institution" in values for values in (flags or {}).values())
                if specialist:
                    continue
                future_event = any(period < event_date <= _months_after(period, 12)
                                   for event_date, _event in event_windows.get(bank_id, []))
                alert = alert_by_key.get((bank_id, period))
                triggered = bool(alert and _level_hit(alert["level"], threshold))
                all_alerts += int(triggered)
                if future_event:
                    event_alerts += int(triggered)
                else:
                    eligible_non_event_periods += 1
                    false_alerts += int(triggered)
        metrics[threshold]["precision_percent"] = (
            100 * event_alerts / all_alerts if all_alerts else None
        )
        metrics[threshold]["false_alarm_rate_percent"] = (
            100 * false_alerts / eligible_non_event_periods
            if eligible_non_event_periods else None
        )
    return {
        "profile": profile.get("profile"),
        "profile_sha256": profile_sha,
        "set": set_name,
        "events": event_rows,
        "evaluable_events": len(evaluable),
        "metrics": metrics,
    }


def write_report(results: list[dict[str, Any]], path: str | Path) -> None:
    lines = [
        "# Stage 4d: event-based rule evaluation",
        "",
        "Windows are the exact calendar interval from 12 to 3 months before "
        "each event date. An event is evaluable when at least one panel "
        "observation exists in that interval.",
        "",
        "| set | profile SHA | evaluable events | threshold | hit rate | Wilson 95% CI | median lead (months) | false-alarm rate | precision |",
        "|---|---|---:|---|---:|---|---:|---:|---:|",
    ]
    for result in results:
        for threshold, metric in result["metrics"].items():
            ci = metric["wilson_95_percent"]
            ci_text = f"{ci[0]:.1f}--{ci[1]:.1f}%" if ci[0] is not None else "—"
            lines.append(
                f"| {result['set']} | `{result['profile_sha256'][:12]}` | "
                f"{metric['evaluable_events']} | {threshold} | "
                f"{metric['hit_rate_percent']:.1f}% | {ci_text} | "
                f"{metric['lead_time_months']['median'] or '—'} | "
                f"{metric['false_alarm_rate_percent']:.1f}% | "
                f"{metric['precision_percent']:.1f}% |"
            )
    lines += ["", "## Per-event observations", "",
              "| set | bank | event date | type | eligible | observations |",
              "|---|---|---|---|---|---|"]
    for result in results:
        for event in result["events"]:
            observations = "; ".join(
                f"{row['period']} {row['level']} ({row['reason']})"
                for row in event["observations"]
            ) or "—"
            lines.append(
                f"| {result['set']} | {event.get('bank_name', event['bank_lei'])} | "
                f"{event['event_date']} | {event['event_type']} | "
                f"{'yes' if event['eligible'] else 'no'} | {observations} |"
            )
    lines += [
        "",
        "## Limitations",
        "",
        "The primary set contains nine events. Semi-annual data provides at "
        "most two observations in the window before 2018-09. The sensitivity "
        "set includes exogenous events, and the 2020-06 NPL definition change "
        "can make comparisons not evaluated. This is an observational "
        "evaluation with no profile tuning.",
        "",
        "## Thesis note",
        "",
        "The evaluation tests whether a frozen, interpretable alert profile "
        "provides advance signal before documented distress events without "
        "using event outcomes to tune thresholds.",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

#todo implements a module with  api for rules