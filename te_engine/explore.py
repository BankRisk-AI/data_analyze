"""Filtering, aggregation and pivoting on the long-format EBA tables (any dataset, any set of years)."""
from __future__ import annotations
import pandas as pd

FUNCS = {"sum": "sum", "mean": "mean", "median": "median", "min": "min", "max": "max", "count": "count", "nunique": "nunique"}
DIM_COLS = {"oth": ["assets_fv", "assets_stages", "exposure", "financial_instruments", "fin_end_year", "n_quarters"],
            "cre": ["portfolio", "country", "country_rank", "exposure", "status", "perf_status", "nace_codes"],
            "mrk": ["portfolio", "mkt_modprod", "mkt_risk"], "sov": ["country", "accounting_portfolio", "maturity"]}

def catalog_items(df: pd.DataFrame) -> pd.DataFrame:
    """One row per standardised item: label, number of banks and rows (use it to find the indicator you need)."""
    g = df.groupby("item_std").agg(label=("label", "first"), banks=("lei", "nunique"), rows=("amount", "size"),
                                   years=("year", lambda s: ",".join(map(str, sorted(set(s)))))).reset_index()
    return g.sort_values("item_std")

def filter_long(df: pd.DataFrame, years=None, periods=None, countries=None, leis=None, item_std=None,
                label_contains: str | None = None, dims: dict | None = None, drop_zero: bool = False) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if years: m &= df["year"].isin(years)
    if periods: m &= df["period"].isin(periods)
    if countries: m &= df["country_bank"].isin(countries)
    if leis: m &= df["lei"].isin(leis)
    if item_std: m &= df["item_std"].isin(item_std)
    if label_contains: m &= df["label"].str.contains(label_contains, case=False, na=False, regex=False)
    for col, vals in (dims or {}).items():
        if vals and col in df.columns: m &= df[col].isin(vals)
    if drop_zero: m &= df["amount"].fillna(0) != 0
    return df[m]

def aggregate_long(df: pd.DataFrame, by: list[str], func: str = "sum", value: str = "amount") -> pd.DataFrame:
    if not by: return pd.DataFrame({value: [getattr(df[value], FUNCS[func])()]})
    out = df.groupby(by, dropna=False)[value].agg(FUNCS[func]).reset_index()
    return out.rename(columns={value: f"{func}_{value}"})

def pivot_long(df: pd.DataFrame, index: list[str], columns: list[str], func: str = "sum", value: str = "amount") -> pd.DataFrame:
    return pd.pivot_table(df, index=index, columns=columns, values=value, aggfunc=FUNCS[func])

def add_decoded(df: pd.DataFrame, meta_path: str | None, dims=("exposure", "perf_status", "nace_codes", "portfolio", "status", "country")) -> pd.DataFrame:
    """Adds <dim>_decoded columns from the sheets of TR_Metadata (original decoding tables of the EBA)."""
    if not meta_path: return df
    sheet = {"exposure": "Exposure", "perf_status": "Perf_status", "nace_codes": "NACE_codes", "portfolio": "Portfolio",
             "status": "Status", "country": "Country"}
    out = df.copy()
    for d in dims:
        if d not in out.columns: continue
        t = pd.read_excel(meta_path, sheet_name=sheet[d], header=None, dtype=str).dropna(how="all").dropna(axis=1, how="all")
        t = t.iloc[:, :2]; t.columns = ["code", "label"]; t = t[t["code"] != d.title()]
        t = t[~t["code"].str.lower().isin(["exposure", "perf_status", "nace_codes", "portfolio", "status", "country", "nace_codes"])]
        out[d + "_decoded"] = out[d].map(dict(zip(t["code"], t["label"])))
    return out
