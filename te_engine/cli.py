"""Batch entry point:  python -m te_engine [all|inventory|panel|charts|events] --data data --out reports [--years 2019 2020]"""
from __future__ import annotations
import argparse, json, os
import pandas as pd
from .workspace import Workspace
from .inventory import inventory_md
from .quality import panel_checks, missingness, iqr_flags, panel_balance
from .labels import e1_labels, event_report
from . import charts, indicators

def run(data="data", out="reports", years=None, commands=("all",)):
    ws = Workspace(data)
    if not ws.years:
        raise SystemExit(f"No folders data/year_YYYY found under '{data}'. Expected layout: {data}/year_2020/tr_oth*.csv ...")
    years = years or ws.years
    os.makedirs(out, exist_ok=True); os.makedirs(f"{out}/charts", exist_ok=True)
    log: list[str] = []
    do = lambda c: "all" in commands or c in commands
    for y, rep in ws.reports().items():
        if rep["missing_required"]: log.append(f"year_{y}: missing files {rep['missing_required']}")
    p = ws.panel(years, log)
    if do("inventory"):
        with open(f"{out}/data_inventory.md", "w") as f:
            f.write("# Data inventory\n\n" + "\n".join(inventory_md(ws.edition(y)) for y in years))
    if do("panel"):
        p.to_csv(f"{out}/panel.csv", index=False)
        ind = indicators.indicators_df(); ind.to_csv(f"{out}/indicators.csv", index=False)
        with open(f"{out}/quality_report.md", "w") as f:
            f.write("# Quality report\n\n## Checks\n\n" + panel_checks(p).to_markdown(index=False))
            f.write("\n\n## Missing values\n\n" + missingness(p).round(3).to_markdown())
            f.write("\n\n## Panel balance\n\n" + panel_balance(p).to_markdown())
            fl = iqr_flags(p); f.write(f"\n\n## Cross-sectional outlier flags (IQR x 3): {len(fl)}\n\n" + (fl.head(40).to_markdown(index=False) if len(fl) else "none"))
            f.write("\n\n## Decision log\n\n" + "\n".join("- " + l for l in log) + "\n")
    rep = None
    if do("events"):
        lab = e1_labels(p); rep = event_report(p, lab)
        lab.to_csv(f"{out}/labels_e1.csv", index=False)
        with open(f"{out}/event_report.json", "w") as f: json.dump(rep, f, indent=2)
        print(json.dumps(rep, indent=2))
    if do("charts"):
        for name, fn in charts.CHARTS.items():
            fig = fn(p, list(p["lei"].drop_duplicates().head(4))) if name == "Bank trajectories" else fn(p)
            fig.savefig(f"{out}/charts/{name.lower().replace(' ', '_').replace('.', '')}.png", dpi=170, bbox_inches="tight")
    print(f"done: panel {p.shape}, years {years}, outputs in {out}/")
    return p, rep

def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m te_engine")
    ap.add_argument("commands", nargs="*", default=["all"], help="all | inventory | panel | events | charts")
    ap.add_argument("--data", default="data"); ap.add_argument("--out", default="reports")
    ap.add_argument("--years", nargs="*", type=int, default=None)
    a = ap.parse_args(argv)
    return run(a.data, a.out, a.years, tuple(a.commands))

if __name__ == "__main__":
    main()
