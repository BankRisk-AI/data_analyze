from __future__ import annotations

from pathlib import Path

import yaml

from app.core.exceptions import BadRequestError, InvalidParameter, NotFoundError
from app.modules.eba_public_analysis.infrastructure.db import read_session, specialist_leis, validate_page


def _profile_file(name: str) -> dict:
    path = Path("config/rules") / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def _available_profiles(cur) -> list[dict]:
    cur.execute("""SELECT profile_name, profile_sha256, max(created_at)
                   FROM alert GROUP BY profile_name, profile_sha256
                   ORDER BY profile_name, max(created_at) DESC""")
    return [{"profile_name": name, "sha": sha, "short_sha": sha[:12],
             "version": _profile_file(name).get("version")}
            for name, sha, _ in cur.fetchall()]


def _profile_error(profile: str | None, available: list[dict]) -> NotFoundError:
    choices = ", ".join(f"{p['profile_name']} v{p['version'] or '?'} ({p['short_sha']})" for p in available)
    return NotFoundError(f"alert profile {profile or 'eu_eba'} does not exist; available profiles: {choices or 'none'}")


def _resolve_profile(cur, profile: str | None) -> tuple[str, str]:
    available = _available_profiles(cur)
    if not available:
        raise _profile_error(profile, available)
    if profile is None:
        candidates = [p for p in available if p["profile_name"] == "eu_eba"]
        if not candidates:
            raise _profile_error(profile, available)
        return candidates[0]["profile_name"], candidates[0]["sha"]
    named = [p for p in available if p["profile_name"] == profile]
    if named:
        return named[0]["profile_name"], named[0]["sha"]
    if len(profile) == 64:
        matches = [p for p in available if p["sha"] == profile]
    elif len(profile) >= 8:
        matches = [p for p in available if p["sha"].startswith(profile)]
        if len(matches) > 1:
            raise BadRequestError(f"ambiguous alert profile prefix '{profile}'")
    else:
        matches = []
    if matches:
        return matches[0]["profile_name"], matches[0]["sha"]
    raise _profile_error(profile, available)


def _payload_fields(payload) -> tuple[str | None, dict | None]:
    if isinstance(payload, list):
        return None, None
    payload = payload or {}
    return payload.get("level_reason"), payload.get("family_scores")


def _alert_projection(value: tuple, specialist: set[str]) -> dict:
    alert_id, bank_id, lei, bank_name, period, level, score, payload = value
    reason, family_scores = _payload_fields(payload)
    return {"alert_id": alert_id, "bank_id": bank_id, "lei": lei, "bank_name": bank_name,
            "period": period, "level": level, "reason": reason,
            "family_scores": family_scores}


def alert_profiles(schema: str) -> list[dict]:
    with read_session(schema) as (_, cur):
        cur.execute("""SELECT profile_name, profile_sha256, max(created_at),
                              max(CASE WHEN jsonb_typeof(rule_results)='array'
                                       THEN jsonb_array_length(rule_results)
                                       ELSE jsonb_array_length(rule_results->'rules') END)
                       FROM alert GROUP BY profile_name, profile_sha256
                       ORDER BY profile_name, max(created_at) DESC""")
        rows = []
        for name, sha, created, rule_count in cur.fetchall():
            config = _profile_file(name)
            rows.append({"profile_name": name, "version": str(config.get("version")) if config.get("version") is not None else None,
                         "sha": sha, "frozen": config.get("frozen"), "created_at": created.isoformat(),
                         "rule_count": rule_count or 0,
                         "families": ["capital", "asset_quality", "profitability", "dynamics"]})
        return rows


def alert_summary(profile: str | None, schema: str) -> dict:
    with read_session(schema) as (_, cur):
        name, sha = _resolve_profile(cur, profile)
        specialists = specialist_leis()
        cur.execute("""SELECT to_char(v.period_end,'YYYYMM'), a.level, trim(b.lei)
                       FROM alert a JOIN dataset_version v USING(version_id)
                       JOIN bank b USING(bank_id)
                       WHERE a.profile_name=%s AND a.profile_sha256=%s
                       ORDER BY v.period_end""", (name, sha))
        grouped = {}
        for period, level, lei in cur.fetchall():
            if lei in specialists:
                continue
            item = grouped.setdefault(period, {"green": 0, "amber": 0, "red": 0, "not_evaluated": 0})
            item[level] += 1
        periods = []
        for period, counts in grouped.items():
            total = sum(counts.values())
            periods.append({"period": period, "counts": counts,
                            "shares": {key: round(value * 100 / total, 4) if total else 0 for key, value in counts.items()}})
        return {"profile_name": name, "profile_sha256": sha, "periods": periods}


def alerts(period: str, profile: str | None, level: str | None, exclude_specialist: bool,
           page: int, page_size: int, schema: str) -> dict:
    validate_page(page, page_size)
    if len(period) != 6 or not period.isdigit():
        raise InvalidParameter("period must be YYYYMM")
    if level not in {None, "green", "amber", "red", "not_evaluated"}:
        raise InvalidParameter("level is invalid")
    with read_session(schema) as (_, cur):
        name, sha = _resolve_profile(cur, profile)
        specialist = specialist_leis()
        clauses = ["a.profile_name=%s", "a.profile_sha256=%s", "to_char(v.period_end,'YYYYMM')=%s"]
        params: list = [name, sha, period]
        if level:
            clauses.append("a.level=%s"); params.append(level)
        cur.execute(f"""SELECT a.alert_id,a.bank_id,trim(b.lei),b.name,to_char(v.period_end,'YYYYMM'),
                               a.level,a.score,a.rule_results
                        FROM alert a JOIN dataset_version v USING(version_id) JOIN bank b USING(bank_id)
                        WHERE {' AND '.join(clauses)}
                        ORDER BY CASE a.level WHEN 'red' THEN 0 WHEN 'amber' THEN 1 WHEN 'green' THEN 2 ELSE 3 END,
                                 a.score DESC NULLS LAST,b.name,a.bank_id""", params)
        filtered = [row for row in cur.fetchall() if not (exclude_specialist and row[2] in specialist)]
        total = len(filtered)
        rows = [_alert_projection(row, specialist)
                for row in filtered[(page - 1) * page_size:page * page_size]]
        return {"rows": rows, "total": total, "page": page, "page_size": page_size}


def bank_alerts(bank_id: int, profile: str | None, schema: str) -> dict:
    with read_session(schema) as (_, cur):
        cur.execute("SELECT 1 FROM bank WHERE bank_id=%s", (bank_id,))
        if not cur.fetchone():
            raise NotFoundError(f"bank {bank_id} does not exist")
        name, sha = _resolve_profile(cur, profile)
        cur.execute("""SELECT to_char(v.period_end,'YYYYMM'),a.level,a.rule_results
                       FROM alert a JOIN dataset_version v USING(version_id)
                       WHERE a.bank_id=%s AND a.profile_name=%s AND a.profile_sha256=%s
                       ORDER BY v.period_end""", (bank_id, name, sha))
        return {"bank_id": bank_id, "rows": [
            {"period": period, "level": level, "reason": _payload_fields(payload)[0],
             "family_scores": _payload_fields(payload)[1]}
            for period, level, payload in cur.fetchall()
        ]}


def alert_detail(alert_id: int, profile: str | None, schema: str) -> dict:
    with read_session(schema) as (_, cur):
        cur.execute("""SELECT a.alert_id,a.bank_id,a.version_id,to_char(v.period_end,'YYYYMM'),
                              a.level,a.score,a.rule_results,a.profile_name,a.profile_sha256
                       FROM alert a JOIN dataset_version v USING(version_id) WHERE a.alert_id=%s""", (alert_id,))
        row = cur.fetchone()
        if not row:
            raise NotFoundError(f"alert {alert_id} does not exist")
        if profile is not None:
            name, sha = _resolve_profile(cur, profile)
            if row[7] != name or row[8] != sha:
                raise NotFoundError(f"alert {alert_id} does not belong to profile {profile}")
        payload = row[6] or {}
        if isinstance(payload, list):
            payload_dict = {}
            rules = payload
        else:
            payload_dict = payload
            rules = payload.get("rules", [])
        config = _profile_file(row[7])
        return {"alert_id": row[0], "bank_id": row[1], "version_id": row[2], "period": row[3],
                "level": row[4], "score": row[5], "reason": payload_dict.get("level_reason"),
                "family_scores": payload_dict.get("family_scores"), "rules": rules,
                "profile_name": row[7], "profile_version": str(config.get("version")) if config.get("version") is not None else None,
                "profile_sha256": row[8]}
