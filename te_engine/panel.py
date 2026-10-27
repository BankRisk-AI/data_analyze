"""Panel construction: one row per (bank, quarter), indicators derived from the long-format EBA files."""
from __future__ import annotations
import numpy as np, pandas as pd
from . import config as C
from .io import lei_crosswalk, bank_list
from .items import ItemResolver

def _pick(df, item, dims):
    d = df[df["item"] == item]
    for k, v in dims.items():
        if k.lower() in d.columns:
            d = d[d[k.lower()] == v]
    return d

def _norm(x: str) -> str:
    return " ".join(str(x).lower().split())

def resolve_item(res, base, data_labels, log, tag):
    """SDD crosswalk first; fallback: exact (normalised) label match in the data. Every result is label-verified."""
    want = _norm(C.LABELS.get(base, ""))
    code, how = res.resolve(base), "SDD"
    if code is None:
        cands = [i for i, l in data_labels.items() if _norm(l) == want]
        code, how = (cands[0] if len(cands) == 1 else None), "label match (item missing in SDD)"
    if code is None:
        log.append(f"[{tag}] WARNING item {base} unresolved"); return None
    if want and _norm(data_labels.get(code, "")) != want:
        log.append(f"[{tag}] WARNING item {base}->{code}: label differs from expectation, feature skipped"); return None
    if how != "SDD": log.append(f"[{tag}] item {base} resolved by {how} -> {code}")
    return code

def edition_wide(ed: dict, log: list) -> pd.DataFrame:
    oth, cre = ed["oth"], ed["cre"]
    res = ItemResolver(ed["sdd_path"], set(oth["item"]) | set(cre["item"]))
    data_labels = {**dict(zip(cre["item"], cre["label"])), **dict(zip(oth["item"], oth["label"]))}
    log.append(f"[{ed['label']}] item column of the SDD used for this edition: {res.edition_col}")
    cols = {}
    for name, (ds, base, extra) in C.SIMPLE.items():
        code = resolve_item(res, base, data_labels, log, ed["label"])
        if code is None:
            continue
        df = oth if ds == "oth" else cre
        dims = {**(C.ZERO_DIMS_OTH if ds == "oth" else C.ZERO_DIMS_CRE), **extra}
        d = _pick(df, code, dims)
        s = d.groupby(["lei", "period"])["amount"].sum(min_count=1)
        if d.duplicated(["lei", "period"]).any():
            log.append(f"[{ed['label']}] WARNING {name}: several rows per bank-period, summed")
        cols[name] = s
    w = pd.DataFrame(cols)
    # n_quarters of the year-to-date P&L (1 for March, 2 for June for December year-end banks)
    code = resolve_item(res, "2020335", data_labels, log, ed["label"])
    if code is not None and "n_quarters" in oth.columns:
        nq = _pick(oth, code, C.ZERO_DIMS_OTH).drop_duplicates(["lei", "period"]).set_index(["lei", "period"])["n_quarters"]
        w["pl_n_quarters"] = pd.to_numeric(nq, errors="coerce")
    # NACE concentration (Herfindahl-Hirschman index of loans to non-financial corporations by NACE sector)
    ncode = resolve_item(res, C.NACE_ITEM[1], data_labels, log, ed["label"])
    if ncode is not None:
        n = cre[(cre["item"] == ncode) & (cre["perf_status"] == "0") & (cre["nace_codes"] != "0")]
        g = n.groupby(["lei", "period", "nace_codes"])["amount"].sum().reset_index()
        tot = g.groupby(["lei", "period"])["amount"].transform("sum")
        g["share"] = np.where(tot > 0, g["amount"] / tot, np.nan)
        w["nace_hhi"] = g.groupby(["lei", "period"])["share"].apply(lambda s: np.nan if s.isna().all() else float((s ** 2).sum()))
    # IFRS 9 stages of loans at amortised cost (tr_oth, Assets template, dimension ASSETS_Stages)
    scode = resolve_item(res, "2021019", data_labels, log, ed["label"])
    if scode is not None:
        d = oth[(oth["item"] == scode) & (oth["assets_fv"] == "0") & (oth["exposure"] == "0") & (oth["financial_instruments"] == "0")]
        piv = d.pivot_table(index=["lei", "period"], columns="assets_stages", values="amount", aggfunc="sum")
        if {"1", "2", "3"} <= set(piv.columns):
            tot = piv[["1", "2", "3"]].sum(axis=1)
            w["stage2_share"] = (piv["2"] / tot.where(tot > 0))
            w["stage3_assets"] = piv["3"]
    w["edition"] = ed["label"]
    return w.reset_index()

def build_panel(editions: list[dict], log: list) -> pd.DataFrame:
    frames, xw, banks = [], {}, []
    for ed in editions:
        frames.append(edition_wide(ed, log))
        if ed.get("meta_path"):
            xw.update(lei_crosswalk(ed["meta_path"])); banks.append(bank_list(ed["meta_path"]))
    p = pd.concat(frames, ignore_index=True)
    p["lei"] = p["lei"].replace(xw)
    p["quarter"] = pd.to_datetime(p["period"], format="%Y%m").dt.to_period("Q")
    before = len(p)
    p = p.sort_values(["lei", "quarter", "edition"]).drop_duplicates(["lei", "quarter"], keep="last")
    if len(p) < before:
        log.append(f"{before - len(p)} duplicated (bank, quarter) rows across editions: kept the latest edition")
    if banks:
        bl = pd.concat(banks).drop_duplicates("lei", keep="last")
        p = p.merge(bl, on="lei", how="left")
    # derived indicators (ratios stay FRACTIONS: 0.12 = 12%)
    for col in list(C.SIMPLE) + ["nace_hhi", "pl_n_quarters", "stage2_share", "stage3_assets"]:
        if col not in p.columns: p[col] = np.nan
    p["npl_ratio"] = p["npl_gross"] / p["loans_gross"].where(p["loans_gross"] > 0)
    if "pl_n_quarters" in p:
        p["roe_annualised"] = p["net_profit_ytd"] * (4 / p["pl_n_quarters"]) / p["total_equity"].where(p["total_equity"] > 0)
    p = p.sort_values(["lei", "quarter"]).reset_index(drop=True)
    # trends use only an existing previous quarter (no carry-forward across gaps)
    def lag(col, k):
        look = p.set_index(["lei", "quarter"])[col]
        keys = pd.MultiIndex.from_arrays([p["lei"], p["quarter"] - k])
        return look.reindex(keys).to_numpy()
    p["npl_delta_qoq"] = p["npl_ratio"] - lag("npl_ratio", 1)
    p["loan_growth_qoq"] = p["loans_gross"] / lag("loans_gross", 1) - 1
    p["loan_growth_yoy"] = p["loans_gross"] / lag("loans_gross", 4) - 1
    p["cet1_delta_qoq"] = p["cet1_ratio"] - lag("cet1_ratio", 1)
    for k, lvl in C.ALERT_LEVELS.items():
        p[k.replace("_ratio", "") + "_headroom"] = p[k] - lvl
    p["min_headroom"] = p[["cet1_headroom", "tier1_headroom", "total_capital_headroom"]].min(axis=1)
    return p
