"""Event E1 and its bookkeeping (alert levels are fractions)."""
from __future__ import annotations
import numpy as np, pandas as pd
from . import config as C

def breach_flags(p: pd.DataFrame, levels=C.ALERT_LEVELS) -> pd.DataFrame:
    below = pd.DataFrame({k: p[k] < v for k, v in levels.items()})
    known = pd.DataFrame({k: p[k].notna() for k in levels})
    out = p[["lei", "quarter"]].copy()
    out["breach"] = below.any(axis=1) & known.any(axis=1)
    out["compliant"] = (~below).all(axis=1) & known.all(axis=1)
    return out

def e1_labels(p: pd.DataFrame, levels=C.ALERT_LEVELS, horizon: int = C.HORIZON) -> pd.DataFrame:
    """y=1 if compliant at t and a breach is observed in t+1..t+h; y=0 if the whole horizon is observed with
    no breach; NaN (excluded) otherwise (compliance at t not met, or horizon incompletely observed)."""
    f = breach_flags(p, levels)
    br = f.set_index(["lei", "quarter"])["breach"].to_dict()
    ys = []
    for lei, q, comp in zip(f["lei"], f["quarter"], f["compliant"]):
        if not comp:
            ys.append(np.nan); continue
        win = [br.get((lei, q + k)) for k in range(1, horizon + 1)]
        if any(w is True for w in win): ys.append(1.0)
        elif all(w is False for w in win): ys.append(0.0)
        else: ys.append(np.nan)
    out = p[["lei", "quarter"]].copy(); out["compliant_at_t"] = f["compliant"].values; out["y_e1"] = ys
    return out

def event_report(p: pd.DataFrame, lab: pd.DataFrame, min_banks_trainval=10, min_banks_test=5) -> dict:
    f = breach_flags(p)
    lab = lab.merge(p[["lei", "quarter"]], on=["lei", "quarter"])
    pos = lab[lab["y_e1"] == 1]
    return {
        "bank_quarters": len(p), "banks": int(p["lei"].nunique()), "quarters": sorted(map(str, p["quarter"].unique())),
        "observed_breaches_any_quarter": int(f["breach"].sum()),
        "eligible_compliant_at_t": int(lab["compliant_at_t"].sum()),
        "labelled_rows": int(lab["y_e1"].notna().sum()), "positive_rows": int(len(pos)),
        "banks_with_event": int(pos["lei"].nunique()),
        "min_headroom_cet1_pp": float(((p["cet1_ratio"] - C.ALERT_LEVELS["cet1_ratio"]) * 100).min()),
        "min_headroom_tier1_pp": float(((p["tier1_ratio"] - C.ALERT_LEVELS["tier1_ratio"]) * 100).min()),
        "min_headroom_total_pp": float(((p["total_capital_ratio"] - C.ALERT_LEVELS["total_capital_ratio"]) * 100).min()),
        "go_e1": bool(pos["lei"].nunique() >= min_banks_trainval + min_banks_test),
    }
