"""Item codes differ between editions (e.g. 2020102 in 2020, 1920102 in 2019). The data dictionary (SDD)
contains one column per edition; this resolver maps the 2020 base codes to the codes of any edition."""
from __future__ import annotations
import pandas as pd

class ItemResolver:
    def __init__(self, sdd_path: str, edition_items: set[str], base_col_hint: str = "Item_TR_2020S"):
        sdd = pd.read_excel(sdd_path, dtype=str)
        self.cols = [c for c in sdd.columns if c.startswith("Item")]
        overlap = {c: len(set(sdd[c].dropna()) & edition_items) for c in self.cols}
        self.edition_col = max(overlap, key=overlap.get)
        self.overlap = overlap
        base_col = base_col_hint if base_col_hint in sdd.columns else self.cols[0]
        sdd = sdd.dropna(subset=[base_col])
        self.map = dict(zip(sdd[base_col], sdd[self.edition_col]))
        self.labels = dict(zip(sdd[base_col], sdd.get("Label", pd.Series(dtype=str))))
        rev = sdd.dropna(subset=[self.edition_col])
        self.to_base = dict(zip(rev[self.edition_col], rev[base_col]))

    def resolve(self, base_code: str) -> str | None:
        return self.map.get(base_code) if isinstance(self.map.get(base_code), str) else None
