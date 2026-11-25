"""H1b: equal-alert-volume recall (selected ML vs R1) on the final test (§3.6, Table 3.2).

Primary: final test (2022-2024); sensitivity: validation OOF (2017-2021).
v1.1 red recall reported as descriptive only.
"""
from __future__ import annotations
from typing import Any

import numpy as np

from app.modules.eba_ml.application.evaluation.context import RunContext
from app.modules.eba_ml.domain.rules import r1_alert


def compute_h1b(ctx: RunContext, seed: int, replicates: int) -> dict[str, Any]:
    """H1b: equal-alert-volume ML recall vs R1 on the final test (§3.6).

    For each period, R1 fires a fixed alert volume; ML is brought to that volume.
    Bootstrap CI of recall difference; supported if lower bound > 0.
    """
    artifact = ctx.artifact
    r0_levels = (artifact.get("label_meta") or {}).get("r0_levels") or {
        "cet1": 0.07, "tier1": 0.085, "total_capital": 0.105}
    r1_margin = ctx.r1_margin
    rows = ctx.rows

    test_preds = (artifact.get("test_predictions") or {}).get(ctx.selected, {})
    test_mask = np.asarray(
        [2022 <= r["period"].year <= 2024 and ctx.y[i] >= 0
         for i, r in enumerate(rows)], dtype=bool)
    result = _recall_comparison(
        ctx, rows, test_mask, test_preds, r0_levels, r1_margin, seed, replicates,
        window="final_test")

    val_preds = dict((artifact.get("predictions") or {}).get(ctx.selected, {}))
    val_mask = np.asarray(
        [2017 <= r["period"].year <= 2021 and ctx.y[i] >= 0
         for i, r in enumerate(rows)], dtype=bool)
    result["sensitivity_oof"] = _recall_comparison(
        ctx, rows, val_mask, val_preds, r0_levels, r1_margin, seed + 100, replicates,
        window="validation_oof")

    result["v1_1_descriptive"] = _v11_recall(ctx)
    result["fixed_share_sensitivity"] = _fixed_share_sensitivity(
        ctx, rows, test_mask, test_preds, r0_levels, seed, replicates)
    return result


def _recall_comparison(ctx, rows, mask, predictions, r0_levels, r1_margin,
                       seed, replicates, window):
    if not mask.any():
        return {"status": "no_rows", "window": window}
    idx = np.flatnonzero(mask)
    periods = np.asarray([rows[i]["period"].isoformat() for i in idx])
    y = ctx.y[mask]
    ml_scores = np.asarray(
        [predictions.get(f"{rows[i]['bank_id']}:{rows[i]['period'].isoformat()}", np.nan)
         for i in idx], dtype=float)
    r1 = np.asarray([int(r1_alert(rows[i], r0_levels, r1_margin)) for i in idx])
    bank_ids = np.asarray([rows[i]["bank_id"] for i in idx])

    ml_sel = _equal_volume_selection(periods, ml_scores, r1)
    pos = y == 1
    n_pos = int(pos.sum())
    if n_pos == 0:
        return {"status": "no_positives", "window": window}

    r1_recall = float((r1.astype(bool) & pos).sum()) / n_pos
    ml_recall = float((ml_sel & pos).sum()) / n_pos
    ci = _cluster_recall_bootstrap(y, ml_sel, r1.astype(bool), bank_ids, seed, replicates)
    return {
        "window": window, "n_rows": int(mask.sum()), "n_positives": n_pos,
        "r1_recall": r1_recall, "ml_recall": ml_recall,
        "recall_diff": ml_recall - r1_recall,
        "ci95": ci, "supported": ci[0] > 0,
    }


def _equal_volume_selection(periods, scores, r1_alerts):
    selected = np.zeros(len(scores), dtype=bool)
    for period in np.unique(periods):
        idx = np.flatnonzero(periods == period)
        count = int(r1_alerts[idx].sum())
        if count and np.isfinite(scores[idx]).any():
            finite = idx[np.isfinite(scores[idx])]
            order = finite[np.argsort(-scores[finite], kind="stable")]
            selected[order[:count]] = True
    return selected


def _cluster_recall_bootstrap(y, ml_sel, r1_sel, banks, seed, n):
    rng = np.random.default_rng(seed)
    unique_banks = np.unique(banks)
    bank_indices = {b: np.flatnonzero(banks == b) for b in unique_banks}
    n_banks = len(unique_banks)
    pos = y == 1
    values = np.empty(n)
    for draw in range(n):
        chosen = rng.integers(0, n_banks, n_banks)
        idx = np.concatenate([bank_indices[unique_banks[c]] for c in chosen])
        p = int(pos[idx].sum())
        values[draw] = (0.0 if p == 0 else
                        float((ml_sel[idx] & pos[idx]).sum()) / p -
                        float((r1_sel[idx] & pos[idx]).sum()) / p)
    return [float(np.quantile(values, .025)), float(np.quantile(values, .975))]


def _r1_headroom(row: dict, r0_levels: dict) -> float:
    """Min headroom across capital ratios (negative = already breaching)."""
    cet1 = row.get("cet1_ratio")
    t1 = row.get("tier1_ratio")
    tc = row.get("total_capital_ratio")
    if cet1 is None or t1 is None or tc is None:
        return float("inf")
    return min(cet1 - r0_levels["cet1"],
               t1 - r0_levels["tier1"],
               tc - r0_levels["total_capital"])


def _fixed_share_sensitivity(ctx, rows, mask, predictions, r0_levels,
                             seed, replicates) -> dict[str, Any]:
    """Recall at fixed 10% and 20% alert shares (post-hoc, with cluster bootstrap CI).

    R1 baseline at each share: top-k by smallest headroom (continuous R1 ranking).
    ML baseline: top-k by ML score. Both compared against true positives.
    """
    if not mask.any():
        return {"status": "no_rows"}
    idx = np.flatnonzero(mask)
    y = ctx.y[mask]
    ml_scores = np.asarray(
        [predictions.get(f"{rows[i]['bank_id']}:{rows[i]['period'].isoformat()}", np.nan)
         for i in idx], dtype=float)
    bank_ids = np.asarray([rows[i]["bank_id"] for i in idx])
    r1 = np.asarray([int(r1_alert(rows[i], r0_levels, ctx.r1_margin)) for i in idx])
    # Headroom: smaller = more at risk; sort ascending to rank R1 candidates
    headroom = np.asarray([_r1_headroom(rows[i], r0_levels) for i in idx], dtype=float)
    r1_share_pct = float(100 * r1.sum() / len(r1))

    pos = y == 1
    n_pos = int(pos.sum())
    if n_pos == 0:
        return {"status": "no_positives"}

    result: dict[str, Any] = {"r1_alert_share_pct": r1_share_pct}
    for share_pct in (10, 20):
        k = max(1, round(len(ml_scores) * share_pct / 100))
        finite = np.flatnonzero(np.isfinite(ml_scores))
        order = finite[np.argsort(-ml_scores[finite], kind="stable")]
        ml_sel = np.zeros(len(ml_scores), dtype=bool)
        ml_sel[order[:k]] = True

        # R1 at same fixed share: top-k by smallest headroom (continuous ranking)
        r1_sel_fixed = np.zeros(len(headroom), dtype=bool)
        r1_sel_fixed[np.argsort(headroom, kind="stable")[:k]] = True

        ml_recall = float((ml_sel & pos).sum()) / n_pos
        r1_recall_fixed = float((r1_sel_fixed & pos).sum()) / n_pos
        ci = _cluster_recall_bootstrap(y, ml_sel, r1_sel_fixed, bank_ids,
                                       seed + share_pct, replicates)
        result[f"share_{share_pct}pct"] = {
            "k_alerts": k,
            "ml_recall": ml_recall,
            "r1_recall": r1_recall_fixed,
            "recall_diff": ml_recall - r1_recall_fixed,
            "ci95": ci,
        }
    return result


def _v11_recall(ctx: RunContext) -> dict[str, Any]:
    """Query v1.1 red alerts and compute recall at their own volume (descriptive)."""
    import yaml
    from pathlib import Path as _Path
    cfg = yaml.safe_load(_Path("config/ml.yaml").read_text())
    profile_sha = cfg.get("comparator_profile_sha", "")
    try:
        with ctx.conn.cursor() as cur:
            cur.execute("""
                SELECT a.bank_id, v.period_end
                FROM alert a
                JOIN dataset_version v USING(version_id)
                WHERE a.level = 'red'
                  AND v.is_active
                  AND a.profile_sha256 = %s
                ORDER BY v.period_end, a.bank_id
            """, (profile_sha,))
            rows_v11 = {(bid, p) for bid, p in cur.fetchall()}
    except Exception as exc:
        return {"status": f"query_failed: {exc}"}

    rows = ctx.rows
    test_mask = np.asarray([2022 <= r["period"].year <= 2024 for r in rows], dtype=bool)
    if not test_mask.any():
        return {"status": "no_test_rows"}
    y_test = ctx.y[test_mask]
    v11 = np.asarray(
        [int((rows[i]["bank_id"], rows[i]["period"]) in rows_v11)
         for i in np.flatnonzero(test_mask)], dtype=int)
    pos = y_test == 1
    n_pos = int(pos.sum())
    if n_pos == 0:
        return {"status": "no_positives"}
    return {
        "n_alerts": int(v11.sum()),
        "recall": float((v11.astype(bool) & pos).sum()) / n_pos,
        "note": "descriptive only; v1.1 alert volume not matched to ML",
    }
