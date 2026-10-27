"""Reading of one edition folder (files may carry suffixes such as tr_oth_2.csv)."""
from __future__ import annotations
import glob, os
import pandas as pd

def _find(folder: str, pattern: str):
    """Case-insensitive search; for data files .csv is preferred over .xlsx."""
    pats = [pattern] if "*" in pattern and not pattern.endswith(".csv") else [pattern]
    hits = []
    for f in sorted(os.listdir(folder)):
        import fnmatch
        if fnmatch.fnmatch(f.lower(), pattern.lower()):
            hits.append(os.path.join(folder, f))
    return hits[0] if hits else None

def _standardise(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.rename(columns={"lei_code": "lei", "nsa": "country_bank"})
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    for c in df.columns:
        if c != "amount":
            df[c] = df[c].astype("string").str.strip() if c in ("lei", "period", "item") else df[c]
    return df

def read_data_file(path: str) -> pd.DataFrame:
    """Reads an ORIGINAL EBA data file: .csv (cp1252 fallback; the files are not UTF-8) or .xlsx exported by Excel."""
    if path.lower().endswith(".xlsx"):
        df = _standardise(pd.read_excel(path, dtype=str))
        df.attrs["encoding"] = "xlsx"
        return df
    for enc in ("utf-8", "cp1252"):
        try:
            df = _standardise(pd.read_csv(path, dtype=str, encoding=enc))
            df.attrs["encoding"] = enc
            return df
        except UnicodeDecodeError:
            continue
    raise ValueError(f"cannot decode {path}")

read_csv_robust = read_data_file  # backward compatible name

def is_aggregate(df: pd.DataFrame) -> pd.Series:
    """'All other banks' bucket: LEI made only of X characters and/or country code OT."""
    return df["lei"].str.upper().str.fullmatch(r"X+") | (df["country_bank"] == "OT")

def read_edition(folder: str, label: str | None = None) -> dict:
    label = label or os.path.basename(os.path.normpath(folder))
    label = label.replace("year_", "")
    out = {"label": label, "folder": folder}
    for key in ("oth", "cre", "mrk", "sov"):
        p = _find(folder, f"tr_{key}*.csv") or _find(folder, f"tr_{key}*.xlsx")
        if p:
            df = read_data_file(p)
            out[key + "_aggregate_rows"] = int(is_aggregate(df).sum())
            out[key] = df.loc[~is_aggregate(df)].copy()
            out[key + "_path"] = p
    out["sdd_path"] = _find(folder, "SDD*.xlsx")
    out["meta_path"] = _find(folder, "TR_Metadata*.xlsx")
    return out

def lei_crosswalk(meta_path: str) -> dict:
    """Old LEI -> current LEI, from the 'Bank list' sheet (LEIs change between editions)."""
    bl = pd.read_excel(meta_path, sheet_name="Bank list", header=1, dtype=str)
    cur = bl["LEI_Code"].str.strip()
    m = {}
    for c in [c for c in bl.columns if c.startswith("LEI_Code_")]:
        for old, new in zip(bl[c].str.strip(), cur):
            if isinstance(old, str) and isinstance(new, str) and old != new:
                m[old] = new
    return m

def bank_list(meta_path: str) -> pd.DataFrame:
    bl = pd.read_excel(meta_path, sheet_name="Bank list", header=1, dtype=str)
    bl = bl.rename(columns={"LEI_Code": "lei", "Name": "bank_name", "Finrep": "finrep", "Country": "country_bank"})
    bl["lei"] = bl["lei"].str.strip()
    bl["finrep_reported"] = ~bl["finrep"].fillna("").str.upper().str.startswith("NO")
    return bl[["lei", "bank_name", "country_bank", "finrep", "finrep_reported"]]
