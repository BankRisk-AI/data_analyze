"""scripts/count_events.py — Stage T-0: count instability events (read-only).

Thesis §3 definitions imported from domain/labels.py (single source of truth).
  E2(t) = 1 if CET1(t+12m) - CET1(t) <= -threshold (forward decline).
  E3(t) = 1 if NPL(t+12m) - NPL(t) >= threshold (forward increase).
  Threshold = quantile over compliant training rows with t+12m observed.
  Windows: train+val = 2014-01..2021-12; test = 2022-01..2024-12.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date
from pathlib import Path

import psycopg2
import yaml
from dotenv import load_dotenv

from app.modules.eba_ml.domain.labels import (
    build_labels,
    compliant,
    compute_tail_threshold,
    _add_months,
    _any_breach,
    _forward_four_q_change,
)

load_dotenv()

R0 = {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105}
TRAIN_START = date(2014, 1, 1)
TRAIN_END   = date(2021, 12, 31)
TEST_START  = date(2022, 1, 1)
TEST_END    = date(2024, 12, 31)
NPL_BREAK   = date(2020, 6, 30)
HORIZON_MONTHS = 12


def window(d: date) -> str:
    if TRAIN_START <= d <= TRAIN_END:
        return "train_val"
    if TEST_START <= d <= TEST_END:
        return "test"
    return "out"


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("""
        SELECT p.bank_id, b.name, v.period_end,
               p.cet1_ratio, p.tier1_ratio, p.total_capital_ratio, p.npl_ratio
        FROM panel_row p
        JOIN dataset_version v USING(version_id)
        JOIN bank b USING(bank_id)
        WHERE v.is_active
        ORDER BY v.period_end, p.bank_id
    """)
    raw = cur.fetchall()
    conn.close()

    # Build rows with field names matching domain/labels.py
    rows = []
    by_bank: dict[int, list] = defaultdict(list)
    by_bank_period: dict[tuple, dict] = {}
    for bank_id, name, period, cet1, tier1, total_cap, npl in raw:
        r = dict(bank_id=bank_id, name=name, period=period,
                 cet1_ratio=cet1, tier1_ratio=tier1,
                 total_capital_ratio=total_cap, npl_ratio=npl)
        rows.append(r)
        by_bank[bank_id].append(r)
        by_bank_period[(bank_id, period)] = r
    for v in by_bank.values():
        v.sort(key=lambda x: x["period"])

    # E2/E3 counts at multiple quantiles using domain build_labels
    print("=" * 70)
    print("T-0 INSTABILITY EVENT COUNTS (forward labels, domain/labels.py)")
    print("=" * 70)
    print(f"\n{'q':>6}  {'CET1-thr':>10}  {'NPL-thr':>10}  "
          f"{'E2 tv rows':>10}  {'E2 tv banks':>12}  "
          f"{'E2 te rows':>10}  {'E2 te banks':>12}  "
          f"{'E3 tv rows':>10}  {'E3 tv banks':>12}  "
          f"{'E3 te rows':>10}  {'E3 te banks':>12}  min_ok?")

    for q in (0.90, 0.95, 0.975):
        y_e2, inc_e2, meta_e2 = build_labels(
            rows, "E2", q, HORIZON_MONTHS, R0, NPL_BREAK, train_cutoff_year=2020)
        y_e3, inc_e3, meta_e3 = build_labels(
            rows, "E3", q, HORIZON_MONTHS, R0, NPL_BREAK, train_cutoff_year=2020)

        def _counts(y, included, label_y):
            tv_rows, tv_banks, te_rows, te_banks = 0, set(), 0, set()
            for i, row in enumerate(rows):
                if not included[i]:
                    continue
                win = window(row["period"])
                if win == "train_val" and y[i] == 1:
                    tv_rows += 1
                    tv_banks.add(row["bank_id"])
                elif win == "test" and y[i] == 1:
                    te_rows += 1
                    te_banks.add(row["bank_id"])
            return tv_rows, len(tv_banks), te_rows, len(te_banks)

        e2r, e2b_tv, e2te, e2b_te = _counts(y_e2, inc_e2, "E2")
        e3r, e3b_tv, e3te, e3b_te = _counts(y_e3, inc_e3, "E3")

        min_ok = "YES" if (e2b_tv >= 10 and e2b_te >= 5 and
                           e3b_tv >= 10 and e3b_te >= 5) else "NO"
        print(f"  {q:.3f}  {meta_e2['cet1_decline_threshold']:>10.5f}  "
              f"{meta_e3['npl_increase_threshold']:>10.5f}  "
              f"{e2r:>10}  {e2b_tv:>12}  {e2te:>10}  {e2b_te:>12}  "
              f"{e3r:>10}  {e3b_tv:>12}  {e3te:>10}  {e3b_te:>12}  {min_ok}")

    # E2_or_E3 combined
    print("\n--- E2_or_E3 combined (q=0.95) ---")
    y_comb, inc_comb, meta_comb = build_labels(
        rows, "E2_or_E3", 0.95, HORIZON_MONTHS, R0, NPL_BREAK, train_cutoff_year=2020)
    tv_r, tv_b, te_r, te_b = 0, set(), 0, set()
    for i, row in enumerate(rows):
        if not inc_comb[i]:
            continue
        win = window(row["period"])
        if win == "train_val" and y_comb[i] == 1:
            tv_r += 1; tv_b.add(row["bank_id"])
        elif win == "test" and y_comb[i] == 1:
            te_r += 1; te_b.add(row["bank_id"])
    print(f"  train_val: {tv_r} rows, {len(tv_b)} banks")
    print(f"  test:      {te_r} rows, {len(te_b)} banks")
    print(f"  excluded:  {meta_comb['excluded_counts']}")
    print(f"  thresholds: CET1={meta_comb['cet1_decline_threshold']:.5f} "
          f"NPL={meta_comb['npl_increase_threshold']:.5f}")


if __name__ == "__main__":
    main()
