"""Load comparator rule scores from the database (§3.3, Table 3.3).

Queries the alert table for a fixed profile SHA and computes two rule-based
baselines (B4, B2) from the panel rows.
"""
from __future__ import annotations

from typing import Any


def load_comparator_scores(
    conn,
    dataset: dict[str, Any],
    profile_sha: str,
) -> dict[str, dict]:
    """Return per-(bank_id, period) scores for v1.1, B4, and B2 baselines.

    v1.1 score: sum of family scores from the rule engine (Table 3.3).
    B4: 1 if NPL > 8% or CET1 < 11% (§3.3).
    B2: 1 if CET1 < 11% only (§3.3).

    Returns {comparator_name: {(bank_id, period): float}}.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT a.bank_id, v.period_end, a.level, a.rule_results
               FROM alert a JOIN dataset_version v USING(version_id)
               WHERE a.profile_sha256=%s""",
            (profile_sha,),
        )
        alert_rows = {
            (bank, period): (level, payload)
            for bank, period, level, payload in cur.fetchall()
        }
    scores: dict[str, dict] = {"v1.1 score": {}, "B4": {}, "B2": {}}
    for row in dataset["rows"]:
        key = (row["bank_id"], row["period"])
        _level, payload = alert_rows.get(key, ("not_evaluated", {}))
        family_scores = (payload or {}).get("family_scores", {})
        scores["v1.1 score"][key] = sum(
            float(value.get("score", 0)) for value in family_scores.values()
        )
        npl, cet1 = row["npl_ratio"], row["cet1_ratio"]
        scores["B4"][key] = float(
            (npl is not None and npl > 0.08) or (cet1 is not None and cet1 < 0.11)
        )
        scores["B2"][key] = float(cet1 is not None and cet1 < 0.11)
    return scores
