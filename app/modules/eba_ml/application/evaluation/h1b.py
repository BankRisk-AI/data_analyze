"""H1b: equal alert-volume recall comparison (§3.6).

Each period receives exactly the v1.1 red alert count, selecting highest model scores.
Computes ml_recall vs v1_1_recall on OOF periods.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.eba_ml.application.evaluation.context import RunContext

EU_EBA_V1_1_PROFILE_SHA = "28a28fa0f89da8435abdb0d6042a69cb2bff421c456926374dd202e0089f7e40"


def compute_h1b(ctx: RunContext, conn) -> dict[str, Any]:
    """Compute equal-alert-volume recall for selected model vs v1.1 rule (H1b, §3.6).

    Returns ml_recall and v1_1_recall on OOF periods only.
    Rule: select the top-k ML scores per period where k = number of v1.1 red alerts.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT a.bank_id, v.period_end, a.rule_results
               FROM alert a JOIN dataset_version v USING(version_id)
               WHERE a.profile_sha256=%s""",
            (EU_EBA_V1_1_PROFILE_SHA,),
        )
        alert = {(b, p): payload or {} for b, p, payload in cur.fetchall()}

    rows = ctx.rows
    rule = np.asarray([
        sum(float(v.get("score", 0))
            for v in alert.get((r["bank_id"], r["period"]), {})
                .get("family_scores", {}).values())
        for r in rows
    ])

    selected_scores = ctx.arrays[ctx.selected]
    mask = np.isfinite(selected_scores)
    selected_alert = np.zeros(len(ctx.y), bool)
    rule_alert = rule > 0

    for p in np.unique(ctx.period[mask]):
        idx = np.flatnonzero(ctx.period == p)
        count = int(rule_alert[idx].sum())
        if count:
            selected_alert[idx[np.argsort(-selected_scores[idx], kind="stable")[:count]]] = True

    oof_pos = max(1, ctx.y[mask].sum())
    return {
        "selected_model": ctx.selected,
        "ml_recall": float((selected_alert[mask] & (ctx.y[mask] == 1)).sum() / oof_pos),
        "v1_1_recall": float((rule_alert[mask] & (ctx.y[mask] == 1)).sum() / oof_pos),
    }
