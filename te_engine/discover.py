"""Discovery of the edition folders. Data layout: data/year_2019/, data/year_2020/, ... (original EBA files inside)."""
from __future__ import annotations
import os, re

def find_year_folders(root: str = "data") -> dict[int, str]:
    out = {}
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        m = re.fullmatch(r"year_(\d{4})", name)
        path = os.path.join(root, name)
        if m and os.path.isdir(path):
            out[int(m.group(1))] = path
    return out

REQUIRED = ["tr_oth", "tr_cre", "tr_mrk"]
OPTIONAL = ["tr_sov"]

def folder_report(path: str) -> dict:
    """Which original files are present in an edition folder (csv or xlsx data files, SDD and TR_Metadata workbooks)."""
    files = os.listdir(path)
    low = [f.lower() for f in files]
    def has(prefix, exts): return any(f.startswith(prefix) and f.endswith(exts) for f in low)
    rep = {p: has(p, (".csv", ".xlsx")) for p in REQUIRED + OPTIONAL}
    rep["SDD"] = has("sdd", (".xlsx",)); rep["TR_Metadata"] = has("tr_metadata", (".xlsx",))
    rep["missing_required"] = [k for k in REQUIRED + ["SDD", "TR_Metadata"] if not rep[k]]
    return rep
