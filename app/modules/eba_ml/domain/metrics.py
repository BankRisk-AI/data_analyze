"""Pure statistical functions for ML evaluation.

No imports from application, infrastructure, or presentation layers.
"""
from __future__ import annotations

import numpy as np

# Default random seed — must match the pipeline seed for reproducible CIs.
_SEED = 20261121


def _classification_metrics(actual, scores):
    from sklearn.metrics import average_precision_score, roc_auc_score
    actual = np.asarray(actual, dtype=int)
    scores = np.asarray(scores, dtype=float)
    return {"hit_rate": float(((scores >= .5) & (actual == 1)).sum() / max(1, actual.sum())),
            "false_alarm_rate": float(((scores >= .5) & (actual == 0)).sum() /
                                      max(1, (actual == 0).sum())),
            "pr_auc": float(average_precision_score(actual, scores)),
            "roc_auc": float(roc_auc_score(actual, scores)) if len(set(actual)) > 1 else None}


def _cluster_bootstrap(actual, candidate, reference, banks, seed=_SEED, n=2000):
    from sklearn.metrics import average_precision_score
    rng = np.random.default_rng(seed)
    groups, inverse = np.unique(np.asarray(banks), return_inverse=True)
    group_indices = tuple(np.flatnonzero(inverse == i) for i in range(len(groups)))
    values = np.empty(n, dtype=float)
    for draw, chosen in enumerate(rng.integers(0, len(groups), size=(n, len(groups)))):
        indices = np.concatenate(tuple(group_indices[i] for i in chosen))
        values[draw] = (average_precision_score(actual[indices], candidate[indices]) -
                        average_precision_score(actual[indices], reference[indices]))
    return [float(np.quantile(values, .025)), float(np.quantile(values, .975))]


def holm_adjust(pvalues: list[float]) -> list[float]:
    """Return Holm step-down adjusted p-values in the original order."""
    indexed = sorted(enumerate(pvalues), key=lambda item: item[1])
    adjusted = [0.0] * len(pvalues)
    running = 0.0
    for rank, (index, value) in enumerate(indexed):
        running = max(running, min(1.0, (len(pvalues) - rank) * value))
        adjusted[index] = running
    return adjusted


def equal_alert_volume_recall(periods, labels, scores, benchmark):
    """Recall when each period receives exactly the benchmark's alert volume."""
    periods = np.asarray(periods)
    labels = np.asarray(labels, dtype=int)
    scores = np.asarray(scores, dtype=float)
    benchmark = np.asarray(benchmark, dtype=bool)
    selected = np.zeros(len(labels), dtype=bool)
    for period in np.unique(periods):
        indices = np.flatnonzero(periods == period)
        count = int(benchmark[indices].sum())
        if count:
            order = indices[np.argsort(-scores[indices], kind="stable")[:count]]
            selected[order] = True
    positives = labels == 1
    return float((selected & positives).sum() / positives.sum()) if positives.any() else 0.0


def lead_time_quarters(event_date, observations, ml_alerts, rule_alerts):
    """Compute t_rule - t_ml in quarters, including first-observation censoring."""
    before = sorted((p for p in observations if p < event_date))
    if not before:
        return None

    def first_run(alerts):
        eligible = [p for p in before if p in alerts]
        if not eligible:
            return None, False
        start = eligible[0]
        first = before[0]
        return start, start == first

    ml_start, ml_censored = first_run(set(ml_alerts))
    rule_start, rule_censored = first_run(set(rule_alerts))
    if ml_start is None or rule_start is None:
        return {"lead_quarters": None, "censored": ml_censored or rule_censored}
    return {"lead_quarters": (rule_start.year * 4 + (rule_start.month - 1) // 3) -
            (ml_start.year * 4 + (ml_start.month - 1) // 3),
            "censored": ml_censored or rule_censored}


def _hyp_bootstrap(y, candidate, reference, banks, metric, seed=_SEED, n=2000):
    from sklearn.metrics import average_precision_score, roc_auc_score
    _, inverse = np.unique(banks, return_inverse=True)
    groups = tuple(np.flatnonzero(inverse == i) for i in range(inverse.max() + 1))
    rng = np.random.default_rng(seed)
    values = np.empty(n)
    fn = average_precision_score if metric == "pr" else roc_auc_score
    for draw in range(n):
        chosen = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate(tuple(groups[i] for i in chosen))
        values[draw] = fn(y[idx], candidate[idx]) - fn(y[idx], reference[idx])
    return {"estimate": float(fn(y, candidate) - fn(y, reference)),
            "ci95": [float(np.quantile(values, .025)), float(np.quantile(values, .975))],
            "p_one_sided": float((np.count_nonzero(values <= 0) + 1) / (n + 1))}


def _hyp_wilcoxon(values):
    values = np.asarray(values, dtype=float)
    values = values[values != 0]
    if len(values) < 5:
        return {"p": None, "n": int(len(values)), "status": "exploratory"}
    from scipy.stats import wilcoxon
    return {"p": float(wilcoxon(values, alternative="greater", method="exact").pvalue),
            "n": int(len(values)), "status": "exact"}
