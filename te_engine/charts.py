"""Charts (English labels). Every function returns a matplotlib Figure; the CLI saves them, the app displays them."""
from __future__ import annotations
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from . import config as C

BLUE, ORANGE, GREEN, RED, GREY = "#2E5C8A", "#A85C32", "#3D7A5E", "#8A2E2E", "#777777"
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False})
RATIOS = {"cet1_ratio": ("CET1 ratio", BLUE), "tier1_ratio": ("Tier 1 ratio", ORANGE), "total_capital_ratio": ("Total capital ratio", GREEN)}

def _empty(msg="No data for the current selection"):
    fig, ax = plt.subplots(figsize=(7, 3)); ax.axis("off"); ax.text(0.5, 0.5, msg, ha="center", va="center"); return fig

def _q(p, quarter):
    return p if quarter in (None, "All") else p[p["quarter"].astype(str) == str(quarter)]

def capital_trend(p: pd.DataFrame, cap: float = 0.5):
    d = p[p["cet1_ratio"] <= cap]
    if d.empty: return _empty()
    fig, ax = plt.subplots(figsize=(9, 4.4)); x = sorted(d["quarter"].unique()); xs = [str(q) for q in x]
    for col, (lab, c) in RATIOS.items():
        g = d.groupby("quarter")[col]; med, q1, q3 = g.median(), g.quantile(.25), g.quantile(.75)
        ax.plot(xs, [med[q] * 100 for q in x], marker="o", color=c, label=f"{lab} (median)")
        ax.fill_between(xs, [q1[q] * 100 for q in x], [q3[q] * 100 for q in x], color=c, alpha=0.12)
        ax.axhline(C.ALERT_LEVELS[col] * 100, color=c, ls="--", lw=1)
    ax.set_ylabel("% of risk exposure amount"); ax.set_xlabel("quarter")
    ax.set_title("Capital Ratios: Median and Interquartile Range vs. Alert Levels", fontweight="bold")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", bbox_to_anchor=(1.01, 1)); fig.tight_layout(); return fig

def capital_distribution(p: pd.DataFrame, ratio="cet1_ratio", quarter=None, cap=0.5):
    d = _q(p, quarter); x = d[ratio].dropna() * 100; x = x[x <= cap * 100]
    if x.empty: return _empty()
    fig, ax = plt.subplots(figsize=(8.4, 4.2))
    ax.hist(x, bins=np.arange(np.floor(x.min()), min(x.max(), cap * 100) + 1.5, 1), color=BLUE, alpha=.85)
    lvl = C.ALERT_LEVELS[ratio] * 100
    ax.axvline(lvl, color=RED, ls="--", lw=2); ax.text(lvl + .2, ax.get_ylim()[1] * .92, f"alert level {lvl:g}%", color=RED, fontsize=9, fontweight="bold", bbox=dict(facecolor="white", alpha=.85, edgecolor="none"))
    ax.axvline(x.min(), color=GREEN, lw=1.6); ax.text(x.min() + .4, ax.get_ylim()[1] * .55, f"lowest: {x.min():.1f}%", color=GREEN, fontsize=9, fontweight="bold", bbox=dict(facecolor="white", alpha=.85, edgecolor="none"))
    hidden = int((d[ratio] > cap).sum())
    if hidden: ax.text(.99, .6, f"{hidden} bank-quarters above {cap*100:g}% not shown", transform=ax.transAxes, ha="right", fontsize=8.2, style="italic", color=GREY)
    ax.set_xlabel(f"{RATIOS[ratio][0]} (%)"); ax.set_ylabel("bank-quarters")
    ax.set_title(f"Distribution of the {RATIOS[ratio][0]} vs. the Alert Level ({quarter or 'all quarters'})", fontweight="bold"); fig.tight_layout(); return fig

def headroom(p: pd.DataFrame):
    d = p.dropna(subset=["min_headroom"])
    if d.empty: return _empty()
    g = d.groupby("quarter")["min_headroom"]; x = sorted(d["quarter"].unique()); xs = [str(q) for q in x]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(xs, [g.min()[q] * 100 for q in x], marker="o", color=RED, label="minimum")
    ax.plot(xs, [g.quantile(.05)[q] * 100 for q in x], marker="o", color=ORANGE, label="5th percentile")
    ax.plot(xs, [g.median()[q] * 100 for q in x], marker="o", color=BLUE, label="median")
    ax.axhline(0, color="black", lw=1.2); ax.text(0.01, 0.04, "below zero = breach of an alert level (event E1)", transform=ax.transAxes, fontsize=8.5, color="black")
    ax.set_ylabel("headroom (percentage points)"); ax.set_xlabel("quarter")
    ax.set_title("Distance to the Nearest Alert Level (Smallest of the Three Capital Headrooms)", fontweight="bold")
    ax.legend(frameon=False, fontsize=8.5); fig.tight_layout(); return fig

def npl_by_country(p: pd.DataFrame, quarter=None, top=12):
    d = _q(p, quarter).dropna(subset=["npl_ratio"])
    if d.empty: return _empty()
    g = d.groupby("country_bank").agg(median=("npl_ratio", "median"), banks=("lei", "nunique")).sort_values("median", ascending=False).head(top)[::-1]
    fig, ax = plt.subplots(figsize=(8.4, 4.6)); ax.barh(g.index, g["median"] * 100, color=ORANGE)
    for y, (v, n) in enumerate(zip(g["median"], g["banks"])): ax.text(v * 100 + .15, y, f"{v*100:.1f}%  (n={n})", va="center", fontsize=8.5)
    ax.set_xlabel("median NPL ratio (%)"); ax.set_title(f"Median NPL Ratio by Country of the Bank ({quarter or 'all quarters'})", fontweight="bold")
    fig.tight_layout(); return fig

def panel_balance(p: pd.DataFrame):
    if p.empty: return _empty()
    n = p.groupby("quarter")["lei"].nunique(); first = p.groupby("lei")["quarter"].min().value_counts().reindex(n.index).fillna(0)
    fig, ax = plt.subplots(figsize=(8.6, 4)); xs = [str(q) for q in n.index]
    ax.bar(xs, n.values, color=BLUE, label="banks in the quarter"); ax.bar(xs, first.values, color=ORANGE, label="first appearance")
    for x, v in zip(xs, n.values): ax.text(x, v + 1, str(v), ha="center", fontsize=8.5)
    ax.set_ylim(0, n.max() * 1.25); ax.set_ylabel("banks"); ax.set_xlabel("quarter"); ax.set_title("Panel Balance: Banks per Quarter", fontweight="bold"); ax.legend(frameon=False, fontsize=8.5, loc="upper left"); fig.tight_layout(); return fig

def missingness(p: pd.DataFrame, cols=None):
    cols = cols or ["cet1_ratio", "leverage_ratio", "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi", "loan_growth_qoq", "loan_growth_yoy", "npl_delta_qoq"]
    cols = [c for c in cols if c in p.columns]
    if p.empty or not cols: return _empty()
    m = p.groupby("quarter")[cols].apply(lambda g: g.isna().mean()).T * 100
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(cols) + 1.8)); im = ax.imshow(m.values, cmap="Reds", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(m.shape[1])); ax.set_xticklabels([str(q) for q in m.columns]); ax.set_yticks(range(len(cols))); ax.set_yticklabels(cols)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]): ax.text(j, i, f"{m.values[i, j]:.0f}", ha="center", va="center", fontsize=8, color="white" if m.values[i, j] > 55 else "black")
    fig.colorbar(im, ax=ax, label="% missing"); ax.set_title("Missing Values by Indicator and Quarter (%)", fontweight="bold"); fig.tight_layout(); return fig

def bank_trajectories(p: pd.DataFrame, leis: list[str], ratio="cet1_ratio"):
    d = p[p["lei"].isin(leis)]
    if d.empty: return _empty("Select at least one bank")
    fig, ax = plt.subplots(figsize=(9, 4.4))
    for lei, g in d.groupby("lei"):
        g = g.sort_values("quarter"); name = g["bank_name"].dropna().iloc[0] if g["bank_name"].notna().any() else lei
        ax.plot([str(q) for q in g["quarter"]], g[ratio] * 100, marker="o", label=str(name)[:34])
    ax.axhline(C.ALERT_LEVELS[ratio] * 100, color=RED, ls="--", lw=1.4, label="alert level")
    ax.set_ylabel(f"{RATIOS[ratio][0]} (%)"); ax.set_xlabel("quarter"); ax.set_title(f"{RATIOS[ratio][0]}: Selected Banks vs. the Alert Level", fontweight="bold")
    ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1)); fig.tight_layout(); return fig

def correlation(p: pd.DataFrame, cols=None):
    cols = cols or ["cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio", "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi"]
    d = p[[c for c in cols if c in p.columns]].dropna()
    if len(d) < 5: return _empty("Not enough complete rows")
    c = d.corr(method="spearman"); fig, ax = plt.subplots(figsize=(7.2, 6)); im = ax.imshow(c.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(c))); ax.set_xticklabels(c.columns, rotation=45, ha="right"); ax.set_yticks(range(len(c))); ax.set_yticklabels(c.columns)
    for i in range(len(c)):
        for j in range(len(c)): ax.text(j, i, f"{c.values[i, j]:.2f}", ha="center", va="center", fontsize=7.5)
    fig.colorbar(im, ax=ax, label="Spearman correlation"); ax.set_title(f"Rank Correlation of Indicators (n = {len(d)})", fontweight="bold"); fig.tight_layout(); return fig

def scatter_cet1_npl(p: pd.DataFrame, quarter=None, cap=0.5):
    d = _q(p, quarter).dropna(subset=["cet1_ratio", "npl_ratio"]); d = d[d["cet1_ratio"] <= cap]
    if d.empty: return _empty()
    fig, ax = plt.subplots(figsize=(7.6, 4.8)); ax.scatter(d["npl_ratio"] * 100, d["cet1_ratio"] * 100, s=22, alpha=.7, color=BLUE)
    ax.axhline(C.ALERT_LEVELS["cet1_ratio"] * 100, color=RED, ls="--", lw=1.4); ax.set_xlabel("NPL ratio (%)"); ax.set_ylabel("CET1 ratio (%)")
    ax.set_title(f"CET1 Ratio vs. NPL Ratio ({quarter or 'all quarters'})", fontweight="bold"); fig.tight_layout(); return fig

CHARTS = {
    "Capital ratios over time": capital_trend, "Capital distribution": capital_distribution, "Distance to alert level": headroom,
    "NPL ratio by country": npl_by_country, "Panel balance": panel_balance, "Missing values": missingness,
    "Bank trajectories": bank_trajectories, "Correlation of indicators": correlation, "CET1 vs. NPL": scatter_cet1_npl}
