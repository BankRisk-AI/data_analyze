"""python -m te_engine.cli --edition data/TE2020 [--edition data/TE2021 ...] --out reports"""
from __future__ import annotations
import argparse, os, json
import pandas as pd
from .io import read_edition
from .inventory import inventory_md
from .panel import build_panel
from .quality import panel_checks, missingness, iqr_flags, panel_balance
from .labels import e1_labels, event_report

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", action="append", required=True, help="folder with one edition's files")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    eds = [read_edition(f) for f in a.edition]
    log: list[str] = []
    with open(f"{a.out}/data_inventory.md", "w") as f:
        f.write("# Data inventory\n\n" + "\n".join(inventory_md(e) for e in eds))
    p = build_panel(eds, log)
    p.to_csv(f"{a.out}/panel.csv", index=False)
    lab = e1_labels(p); rep = event_report(p, lab)
    with open(f"{a.out}/quality_report.md", "w") as f:
        f.write("# Quality report\n\n## Checks\n\n" + panel_checks(p).to_markdown(index=False))
        f.write("\n\n## Missing values\n\n" + missingness(p).round(3).to_markdown())
        f.write("\n\n## Panel balance\n\n" + panel_balance(p).to_markdown())
        fl = iqr_flags(p); f.write(f"\n\n## Cross-sectional outlier flags (IQR x 3): {len(fl)}\n\n" + (fl.head(30).to_markdown(index=False) if len(fl) else "none"))
        f.write("\n\n## Event report (E1)\n\n```\n" + json.dumps(rep, indent=2) + "\n```\n")
        f.write("\n## Decision log\n\n" + "\n".join("- " + l for l in log) + "\n")
    print(json.dumps(rep, indent=2))
    return p, rep

if __name__ == "__main__":
    main()
