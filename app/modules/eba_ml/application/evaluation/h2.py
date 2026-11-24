"""H2: lead-time analysis — does ML alert earlier than the rule? (§3.6).

For each primary event: compute t_A (ML lead) and t_B (rule lead) in quarters,
L = t_A - t_B. OOF events use OOF scores; others use LOEO training.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import yaml
from pathlib import Path

from app.modules.eba_ml.application.dataset import _months, _approved_ids
from app.modules.eba_ml.application.models import model_factory
from app.modules.eba_ml.domain.metrics import _hyp_wilcoxon
from app.modules.eba_ml.application.evaluation.context import RunContext

EU_EBA_V1_1_PROFILE_SHA = "28a28fa0f89da8435abdb0d6042a69cb2bff421c456926374dd202e0089f7e40"


def compute_h2(ctx: RunContext, conn, loeo_limit: int | None) -> dict[str, Any]:
    """Compute per-event lead times and aggregate Wilcoxon test (H2, §3.6).

    t_A = quarters from first matched-FAR ML alert to event date.
    t_B = quarters from first matched-FAR rule alert to event date.
    L = t_A - t_B (positive means ML leads).
    """
    approved = _approved_ids(conn)
    space = ctx.artifact.get("space", "table35")
    params_selected = max(
        ctx.artifact.get("search", {})[ctx.selected],
        key=lambda x: x["mean_pr_auc"])["parameters"]
    rule, global_thresholds = _load_rule_scores_and_thresholds(conn, ctx)
    catalogue = yaml.safe_load(Path("config/events.yaml").read_text()) or {}
    primary_events = [e for e in catalogue.get("events", [])
                      if e.get("set") == "primary" and e.get("status") == "included"]
    h2_events, _ = _process_events(
        primary_events, ctx, ctx.rows, rule, ctx.arrays[ctx.selected],
        np.isfinite(ctx.arrays[ctx.selected]),
        global_thresholds, approved, params_selected, space, loeo_limit)
    eval_nonzero_L = [e["L"] for e in h2_events
                      if e["status"] == "evaluated" and e.get("L") is not None
                      and e["L"] != 0]
    all_reported_L = [e["L"] for e in h2_events
                      if e["status"] in ("evaluated", "censored") and e.get("L") is not None]
    return {
        "thresholds": global_thresholds, "events": h2_events,
        "wilcoxon": _hyp_wilcoxon(eval_nonzero_L),
        "criterion": bool(all_reported_L and np.median(all_reported_L) >= 1),
    }


def _load_rule_scores_and_thresholds(conn, ctx: RunContext) -> tuple:
    """Query rule scores and compute global thresholds for the selected model (H2, §3.6)."""
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
    probs = selected_scores[mask]
    red_share = float(np.mean(rule[mask] > 0))
    thresholds = {
        "matched_far": float(np.quantile(probs, max(0, 1 - red_share))),
        "max_ur_0_9": float(np.quantile(probs, 0.9)),
    }
    return rule, thresholds


def _process_events(
    primary_events: list, ctx: RunContext, rows: list, rule: np.ndarray,
    selected_scores: np.ndarray, mask: np.ndarray,
    global_thresholds: dict, approved: dict, params_selected: dict,
    space: str, loeo_limit: int | None,
) -> tuple[list, int]:
    """Iterate primary events; compute OOF or LOEO lead times per event."""
    h2_events = []
    loeo_done = 0
    for event in primary_events:
        bank = event.get("bank_id")
        lei = (event.get("bank_lei") or "").strip()
        event_id = event.get("event_id")
        edate = date.fromisoformat(event["event_date"])
        win_start = _months(edate, -12)
        win_end = _months(edate, -3)
        all_window_idx = [i for i, r in enumerate(rows)
                          if r["bank_id"] == bank
                          and win_start <= r["period"] <= win_end]
        oof_window_idx = [i for i in np.flatnonzero(mask)
                          if rows[i]["bank_id"] == bank
                          and win_start <= rows[i]["period"] <= win_end]
        if oof_window_idx:
            obs = [(rows[i]["period"], float(selected_scores[i])) for i in oof_window_idx]
            thresholds_used = global_thresholds
            is_loeo = False
            is_oot = True
        else:
            result = _try_loeo(
                ctx, rows, all_window_idx, event_id, bank, lei, edate,
                approved, params_selected, space, rule, loeo_limit, loeo_done)
            if isinstance(result, dict):
                h2_events.append(result)
                continue
            obs, thresholds_used, loeo_done = result
            is_loeo = True
            is_oot = False
        entry = _score_event(
            event_id, edate, obs, thresholds_used, all_window_idx, rows,
            is_oot, is_loeo, rule)
        h2_events.append(entry)
    return h2_events, loeo_done


def _try_loeo(ctx, rows, all_window_idx, event_id, bank, lei, edate,
              approved, params_selected, space, rule, loeo_limit, loeo_done):
    """Attempt LOEO training; return early-exit dict or (obs, thresholds, loeo_done)."""
    if loeo_limit is not None and loeo_done >= loeo_limit:
        return {"event": event_id, "status": "no_ml_prediction",
                "out_of_time": False, "loeo": False,
                "t_A": None, "t_B": None, "L": None}
    if not all_window_idx:
        return {"event": event_id, "status": "no_ml_prediction",
                "out_of_time": False, "loeo": True,
                "t_A": None, "t_B": None, "L": None}
    win_start = _months(edate, -12)
    exclusion = approved.get(lei, {bank})
    loeo_train_idx = np.asarray([
        i for i, r in enumerate(rows)
        if r["bank_id"] not in exclusion and r["period"] <= win_start])
    if len(loeo_train_idx) == 0 or ctx.y[loeo_train_idx].sum() == 0:
        return {"event": event_id, "status": "no_ml_prediction",
                "out_of_time": False, "loeo": True,
                "t_A": None, "t_B": None, "L": None}
    loeo_y = ctx.y[loeo_train_idx]
    loeo_weight = (len(loeo_train_idx) - loeo_y.sum()) / max(1, loeo_y.sum())
    loeo_model = model_factory(ctx.selected, params_selected, loeo_weight, space=space)
    loeo_model.fit(ctx.dataset["X"][loeo_train_idx], loeo_y)
    event_window_idx = np.asarray(all_window_idx)
    loeo_scores = loeo_model.predict_proba(ctx.dataset["X"][event_window_idx])[:, 1]
    obs = [(rows[event_window_idx[j]]["period"], float(loeo_scores[j]))
           for j in range(len(event_window_idx))]
    train_probs = loeo_model.predict_proba(ctx.dataset["X"][loeo_train_idx])[:, 1]
    train_red_share = float(np.mean(rule[loeo_train_idx] > 0))
    thresholds_used = {
        "matched_far": float(np.quantile(train_probs, max(0, 1 - train_red_share))),
        "max_ur_0_9": float(np.quantile(train_probs, 0.9)),
    }
    return obs, thresholds_used, loeo_done + 1


def _score_event(event_id, edate, obs, thresholds_used, all_window_idx,
                 rows, is_oot, is_loeo, rule):
    """Compute t_A, t_B, L for one event and return the event dict."""
    has_rule_alert = any(rule[i] > 0 for i in all_window_idx)
    if not has_rule_alert:
        return {"event": event_id, "status": "rule_no_alert",
                "out_of_time": is_oot, "loeo": is_loeo,
                "t_A": None, "t_B": None, "L": None}
    leads = []
    for thresh in thresholds_used.values():
        hits = [p for p, score in obs if score >= thresh]
        leads.append((edate.year * 4 + (edate.month - 1) // 3) -
                     (hits[-1].year * 4 + (hits[-1].month - 1) // 3) if hits else None)
    t_A, t_B = leads[0], leads[1]
    if t_A is None:
        return {"event": event_id, "status": "ml_no_alert",
                "out_of_time": is_oot, "loeo": is_loeo,
                "t_A": None, "t_B": None, "L": None}
    L = t_A - t_B if t_B is not None else None
    all_bank_periods = sorted(r["period"] for r in rows
                              if r["bank_id"] == rows[all_window_idx[0]]["bank_id"]
                              ) if all_window_idx else []
    first_bank_period = all_bank_periods[0] if all_bank_periods else None
    first_ml_hit = min(
        (p for p, score in obs if score >= thresholds_used["matched_far"]), default=None)
    status = ("censored" if first_ml_hit is not None and first_bank_period is not None
              and first_ml_hit == first_bank_period else "evaluated")
    return {"event": event_id, "status": status,
            "out_of_time": is_oot, "loeo": is_loeo,
            "t_A": t_A, "t_B": t_B, "L": L}
