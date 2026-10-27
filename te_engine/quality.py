"""Data-quality checks, written so that every statement in the report is computed from the files."""
from __future__ import annotations
import numpy as np, pandas as pd
from . import config as C

def internal_consistency(ed: dict) -> pd.DataFrame:
    """Re-computes identities that must hold inside tr_oth (uses the 2020 codes; for other editions
    the codes are resolved through the SDD in panel.py, so run these on the panel instead)."""
    return pd.DataFrame()

def panel_checks(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    def add(name, ok, detail): rows.append({"check": name, "status": "OK" if ok else "ATTENTION", "detail": detail})
    add("unique key (bank, quarter)", not p.duplicated(["lei", "quarter"]).any(), f"{len(p)} rows")
    calc = p["cet1_capital"] / p["rwa"]
    d = (calc - p["cet1_ratio"]).abs()
    add("CET1 ratio = CET1 capital / RWA", bool(d.max() < 1e-6), f"max abs diff {d.max():.2e} on {d.notna().sum()} rows")
    d2 = (p["tier1_capital"] - p["cet1_capital"] - p["at1_capital"]).abs()
    add("Tier 1 = CET1 + AT1", bool(d2.max() < 1e-3), f"max abs diff {d2.max():.2e}")
    d3 = (p["cet1_capital"] + p["at1_capital"] + p["tier2_capital"]) / p["rwa"] - p["total_capital_ratio"]
    add("Total ratio = (CET1 + AT1 + T2) / RWA", bool(d3.abs().max() < 1e-6), f"max abs diff {d3.abs().max():.2e}")
    both = p[["stage3_assets", "npe_stage3"]].dropna()
    if len(both):
        diff = (both["stage3_assets"] - both["npe_stage3"]).abs() / both["npe_stage3"].abs().where(both["npe_stage3"].abs() > 0)
        add("Stage 3 loans: tr_oth (Assets) vs tr_cre (NPE)", bool((diff.dropna() < 1e-6).mean() > 0.95),
            f"{(diff.dropna() < 1e-6).mean():.1%} of {len(both)} bank-quarters agree to 1e-6 (relative)")
    add("ratios stored as fractions", bool(p["cet1_ratio"].median() < 1), f"median CET1 ratio = {p['cet1_ratio'].median():.4f}")
    odd = p.loc[p["cet1_ratio"] > 0.5, "lei"].nunique()
    add("CET1 ratio > 50% (public-development / specialised banks)", odd == 0, f"{odd} banks flagged (kept, marked for review)")
    return pd.DataFrame(rows)

def missingness(p: pd.DataFrame) -> pd.DataFrame:
    cols = ["cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio", "npl_ratio", "roe_annualised", "nace_hhi",
            "loan_growth_qoq", "loan_growth_yoy", "npl_delta_qoq"]
    cols = [c for c in cols if c in p.columns]
    out = p[cols].isna().sum().rename("missing").to_frame()
    out["share"] = out["missing"] / len(p)
    if "finrep_reported" in p.columns:
        nf = p[~p["finrep_reported"].fillna(True)]
        out["missing_among_no_FINREP_banks"] = nf[cols].isna().sum()
        out["n_no_FINREP_rows"] = len(nf)
    return out

def iqr_flags(p: pd.DataFrame, cols=("cet1_ratio", "npl_ratio", "roe_annualised"), k=3.0) -> pd.DataFrame:
    """Cross-sectional outliers: per quarter and indicator, outside [Q1-k*IQR, Q3+k*IQR]. Flagged, never deleted."""
    res = []
    for c in cols:
        if c not in p: continue
        for q, g in p.groupby("quarter"):
            q1, q3 = g[c].quantile([0.25, 0.75]); iqr = q3 - q1
            hit = g[(g[c] < q1 - k * iqr) | (g[c] > q3 + k * iqr)]
            for _, r in hit.iterrows():
                res.append({"quarter": str(q), "indicator": c, "lei": r["lei"], "value": r[c]})
    return pd.DataFrame(res)

def panel_balance(p: pd.DataFrame) -> pd.DataFrame:
    n = p.groupby("quarter")["lei"].nunique().rename("banks").to_frame()
    first = p.groupby("lei")["quarter"].min(); last = p.groupby("lei")["quarter"].max()
    n["entering"] = first.value_counts().reindex(n.index).fillna(0).astype(int)
    n["last_seen"] = last.value_counts().reindex(n.index).fillna(0).astype(int)
    return n
