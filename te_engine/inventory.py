"""Inventory of the raw files: shape, encoding, periods, banks, dimensions, join coverage."""
from __future__ import annotations
import pandas as pd

def inventory_md(ed: dict) -> str:
    L = [f"## Edition {ed['label']}", ""]
    leis = {}
    for k in ("oth", "cre", "mrk", "sov"):
        if k not in ed: L.append(f"- `{k}`: file not found"); continue
        df = ed[k]; leis[k] = set(df["lei"])
        L.append(f"- `{k}` ({ed[k+'_path'].split('/')[-1]}): {len(df):,} rows, encoding {df.attrs.get('encoding')}, "
                 f"{df['lei'].nunique()} banks, periods {sorted(df['period'].unique())}, {df['item'].nunique()} items; "
                 f"aggregate rows dropped: {ed[k+'_aggregate_rows']}")
    if len(leis) > 1:
        base = leis.get("oth", set())
        L.append("- LEI coverage vs tr_oth: " + ", ".join(f"{k}: {len(v & base)}/{len(base)}" for k, v in leis.items()))
    oth = ed["oth"]
    p = oth.groupby("period")["lei"].nunique()
    L.append("- banks per period (tr_oth): " + ", ".join(f"{k}: {v}" for k, v in p.items()))
    once = oth.groupby("lei")["period"].nunique(); once = once[once == 1]
    L.append(f"- banks present in only one period: {len(once)}")
    if "country_bank" in oth:
        L.append(f"- bank country codes: {oth['country_bank'].nunique()} ({'GB' in set(oth['country_bank'])} contains GB)")
    for k in ("oth", "cre"):
        if k in ed:
            dims = [c for c in ed[k].columns if c not in ("lei","country_bank","period","item","label","amount","footnote")]
            L.append(f"- `{k}` dimension columns: {dims}")
    return "\n".join(L) + "\n"
