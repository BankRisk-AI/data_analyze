"""Workspace: loads every data/year_* folder once, exposes harmonised long tables and the bank x quarter panel."""
from __future__ import annotations
import os
import pandas as pd
from .discover import find_year_folders, folder_report
from .io import read_edition
from .items import ItemResolver
from .panel import build_panel

DATASETS = ("oth", "cre", "mrk", "sov")

class Workspace:
    def __init__(self, root: str = "data"):
        self.root = root
        self.folders = find_year_folders(root)
        self.years = sorted(self.folders)
        self._ed: dict[int, dict] = {}
        self._resolver: dict[int, ItemResolver] = {}

    def edition(self, year: int) -> dict:
        if year not in self._ed:
            self._ed[year] = read_edition(self.folders[year], str(year))
        return self._ed[year]

    def reports(self) -> dict:
        return {y: folder_report(p) for y, p in self.folders.items()}

    def resolver(self, year: int) -> ItemResolver | None:
        if year not in self._resolver:
            ed = self.edition(year)
            if not ed.get("sdd_path"):
                return None
            items = set()
            for k in DATASETS:
                if k in ed: items |= set(ed[k]["item"].dropna())
            self._resolver[year] = ItemResolver(ed["sdd_path"], items)
        return self._resolver[year]

    def long(self, dataset: str, years: list[int] | None = None) -> pd.DataFrame:
        """All rows of one dataset (oth, cre, mrk, sov) for the chosen years, with columns year and item_std
        (the item code of the 2020 edition, so the same indicator can be aggregated across years)."""
        frames = []
        for y in (years or self.years):
            ed = self.edition(y)
            if dataset not in ed: continue
            df = ed[dataset].copy()
            res = self.resolver(y)
            df["item_std"] = df["item"].map(res.to_base).fillna(df["item"]) if res else df["item"]
            df.insert(0, "year", y)
            frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def panel(self, years: list[int] | None = None, log: list | None = None) -> pd.DataFrame:
        log = log if log is not None else []
        eds = [self.edition(y) for y in (years or self.years)]
        if not eds: return pd.DataFrame()
        p = build_panel(eds, log)
        p["year"] = p["quarter"].dt.year
        return p

    def bank_names(self) -> pd.DataFrame:
        from .io import bank_list
        frames = [bank_list(self.edition(y)["meta_path"]) for y in self.years if self.edition(y).get("meta_path")]
        return pd.concat(frames).drop_duplicates("lei", keep="last") if frames else pd.DataFrame(columns=["lei", "bank_name"])
