"""scripts/count_events.py — Stage T-0: count instability events (read-only).

Thesis §3 definitions:
  Alert levels: CET1 < 7%, Tier1 < 8.5%, total capital < 10.5%.
  Compliant at t: all three ratios present and all >= alert level.
  E1 label: compliant at t, any level breached in (t, t+12 months].
  Windows: train+val = 2014-12..2021-12; test = 2022-01..2024-12.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import date

import psycopg2
import yaml
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

CET1_LEVEL   = 0.07
TIER1_LEVEL  = 0.085
TOTAL_LEVEL  = 0.105

TRAIN_START = date(2014, 12, 31)
TRAIN_END   = date(2021, 12, 31)
TEST_START  = date(2022, 1, 1)
TEST_END    = date(2024, 12, 31)

HORIZON_MONTHS = 12


def _add_months(d: date, n: int) -> date:
    total = d.year * 12 + d.month - 1 + n
    y, m = divmod(total, 12)
    return date(y, m + 1, d.day)


def window(d: date) -> str:
    if TRAIN_START <= d <= TRAIN_END:
        return "train_val"
    if TEST_START <= d <= TEST_END:
        return "test"
    return "out"


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    # Load panel: active rows, semiannual (Jun/Dec) and all quarters
    cur.execute("""
        SELECT p.bank_id, b.name, v.period_end,
               p.cet1_ratio, p.tier1_ratio, p.total_capital_ratio,
               p.npl_ratio, p.cet1_delta_qoq
        FROM panel_row p
        JOIN dataset_version v USING(version_id)
        JOIN bank b USING(bank_id)
        WHERE v.is_active
        ORDER BY v.period_end, p.bank_id
    """)
    raw = cur.fetchall()
    conn.close()

    # Build lookup: (bank_id, period) -> row dict
    rows = []
    by_bank: dict[int, list] = defaultdict(list)
    for bank_id, name, period, cet1, tier1, total_cap, npl, cet1_dqoq in raw:
        r = dict(bank_id=bank_id, name=name, period=period,
                 cet1=cet1, tier1=tier1, total=total_cap,
                 npl=npl, cet1_dqoq=cet1_dqoq)
        rows.append(r)
        by_bank[bank_id].append(r)

    for v in by_bank.values():
        v.sort(key=lambda x: x["period"])

    # ----- Compliance -----
    def ratios_present(r):
        return r["cet1"] is not None and r["tier1"] is not None and r["total"] is not None

    def compliant(r):
        return (ratios_present(r)
                and r["cet1"] >= CET1_LEVEL
                and r["tier1"] >= TIER1_LEVEL
                and r["total"] >= TOTAL_LEVEL)

    def any_breach(r):
        return (ratios_present(r)
                and (r["cet1"] < CET1_LEVEL
                     or r["tier1"] < TIER1_LEVEL
                     or r["total"] < TOTAL_LEVEL))

    def which_breach(r):
        out = []
        if r["cet1"] is not None and r["cet1"] < CET1_LEVEL:
            out.append(f"CET1={r['cet1']:.3f}")
        if r["tier1"] is not None and r["tier1"] < TIER1_LEVEL:
            out.append(f"Tier1={r['tier1']:.3f}")
        if r["total"] is not None and r["total"] < TOTAL_LEVEL:
            out.append(f"Total={r['total']:.3f}")
        return ", ".join(out) if out else "none"

    # ----- E1 labelling -----
    # For a row at t: look at all bank rows in (t, t+12m]
    def e1_label(r):
        """Returns (label, excluded_reason) where label in {0, 1, None=excluded}."""
        if not compliant(r):
            return None, "non_compliant"
        win = window(r["period"])
        if win == "out":
            return None, "out_of_window"
        horizon_end = _add_months(r["period"], HORIZON_MONTHS)
        future = [x for x in by_bank[r["bank_id"]]
                  if r["period"] < x["period"] <= horizon_end]
        if not future:
            # Already breached before?  Check previous non-compliance.
            already = any(any_breach(x) for x in by_bank[r["bank_id"]]
                          if x["period"] <= r["period"])
            if already:
                return 1, None
            # 2024 rows: horizon may be incomplete
            if r["period"] >= date(2024, 1, 1):
                return None, "incomplete_horizon"
            return None, "no_future_obs"
        breach = any(any_breach(x) for x in future)
        return (1 if breach else 0), None

    # ----- Collect stats -----
    stats = {w: dict(total=0, compliant=0, non_compliant=0,
                     excl_missing=0, excl_incomplete=0, excl_no_future=0,
                     excl_out=0,
                     e1_pos=0, e1_neg=0) for w in ("train_val", "test")}
    e1_banks: dict[str, dict[int, dict]] = {"train_val": {}, "test": {}}

    for r in rows:
        win = window(r["period"])
        if win == "out":
            continue
        s = stats[win]
        s["total"] += 1
        if not ratios_present(r):
            s["excl_missing"] += 1
            s["non_compliant"] += 1  # count as non-compliant for reporting
            continue
        if not compliant(r):
            s["non_compliant"] += 1
            continue
        s["compliant"] += 1
        label, reason = e1_label(r)
        if label is None:
            if reason == "incomplete_horizon":
                s["excl_incomplete"] += 1
            elif reason == "no_future_obs":
                s["excl_no_future"] += 1
            continue
        if label == 1:
            s["e1_pos"] += 1
            bid = r["bank_id"]
            if bid not in e1_banks[win]:
                # find first breach in future
                horizon_end = _add_months(r["period"], HORIZON_MONTHS)
                future = [x for x in by_bank[bid]
                          if r["period"] < x["period"] <= horizon_end and any_breach(x)]
                # Also check past breach for already-breached case
                if not future:
                    future = [x for x in by_bank[bid]
                              if x["period"] <= r["period"] and any_breach(x)]
                fb = min(future, key=lambda x: x["period"]) if future else r
                e1_banks[win][bid] = dict(name=r["name"],
                                          first_breach=fb["period"],
                                          breach_detail=which_breach(fb))
        else:
            s["e1_neg"] += 1

    # ----- E2/E3 preview (compliant rows, 4-quarter CET1 decline and NPL increase) -----
    # Quantile base: 2014-12..2019-12 compliant rows with 4-quarter prior data
    QUANT_START = date(2014, 12, 31)
    QUANT_END   = date(2019, 12, 31)

    by_bank_period = {(r["bank_id"], r["period"]): r for r in rows}

    def four_q_change(r, field):
        """Value at t minus value at t-4 quarters (t-12 months)."""
        prev_period = _add_months(r["period"], -12)
        prev = by_bank_period.get((r["bank_id"], prev_period))
        if prev is None:
            return None
        v0, v1 = prev[field], r[field]
        if v0 is None or v1 is None:
            return None
        return v1 - v0  # positive = increase

    cet1_declines = []  # decline = -change, so positive means CET1 fell
    npl_increases = []
    npl_break_count = 0
    NPL_BREAK = date(2020, 6, 30)

    for r in rows:
        if not compliant(r):
            continue
        p = r["period"]
        if not (QUANT_START <= p <= QUANT_END):
            continue
        dc = four_q_change(r, "cet1")
        if dc is not None:
            cet1_declines.append(-dc)  # decline > 0
        dn = four_q_change(r, "npl")
        if dn is not None:
            prev_p = _add_months(p, -12)
            if prev_p <= NPL_BREAK <= p:
                npl_break_count += 1
            npl_increases.append(dn)

    import statistics
    def quantile(data, q):
        if not data:
            return float("nan")
        data_s = sorted(data)
        idx = q * (len(data_s) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(data_s) - 1)
        return data_s[lo] + (idx - lo) * (data_s[hi] - data_s[lo])

    cet1_q = {q: quantile(cet1_declines, q) for q in (0.90, 0.95, 0.975)}
    npl_q  = {q: quantile(npl_increases,  q) for q in (0.90, 0.95, 0.975)}

    # E2/E3 positive counts by window and threshold
    e2_counts: dict[str, dict[float, dict]] = {w: {} for w in ("train_val", "test")}
    e3_counts: dict[str, dict[float, dict]] = {w: {} for w in ("train_val", "test")}

    for r in rows:
        win = window(r["period"])
        if win == "out":
            continue
        if not compliant(r):
            continue
        horizon_end = _add_months(r["period"], HORIZON_MONTHS)
        future = [x for x in by_bank[r["bank_id"]]
                  if r["period"] < x["period"] <= horizon_end]
        if not future and r["period"] < date(2024, 1, 1):
            continue  # exclude no-future rows same as E1
        dc = four_q_change(r, "cet1")
        dn = four_q_change(r, "npl")
        for q in (0.90, 0.95, 0.975):
            # E2: CET1 4q decline >= threshold (decline = -change)
            if dc is not None:
                e2_counts[win].setdefault(q, dict(rows=0, banks=set()))
                if -dc >= cet1_q[q]:
                    e2_counts[win][q]["rows"] += 1
                    e2_counts[win][q]["banks"].add(r["bank_id"])
            # E3: NPL 4q increase >= threshold
            if dn is not None:
                e3_counts[win].setdefault(q, dict(rows=0, banks=set()))
                if dn >= npl_q[q]:
                    e3_counts[win][q]["rows"] += 1
                    e3_counts[win][q]["banks"].add(r["bank_id"])

    # ----- Primary events cross-check -----
    catalogue = yaml.safe_load(Path("config/events.yaml").read_text()) or {}
    primary_events = [e for e in catalogue.get("events", [])
                      if e.get("set") == "primary" and e.get("status") == "included"]

    conn2 = psycopg2.connect(os.environ["DATABASE_URL"])
    cur2 = conn2.cursor()
    cur2.execute("SELECT bank_id, trim(lei) FROM bank")
    lei_to_id = {lei: bid for bid, lei in cur2.fetchall()}
    conn2.close()

    cross = []
    for ev in primary_events:
        lei = (ev.get("bank_lei") or "").strip()
        bid = lei_to_id.get(lei)
        edate = date.fromisoformat(ev["event_date"])
        eid = ev.get("event_id", lei)
        if bid is None:
            cross.append(f"  {eid}: bank not found")
            continue
        bank_rows = sorted(by_bank.get(bid, []), key=lambda x: x["period"])
        # E1: any compliant row with breach in horizon before event
        e1_hit = any(
            compliant(r) and r["period"] < edate and
            any(any_breach(x) for x in by_bank[bid]
                if r["period"] < x["period"] <= _add_months(r["period"], HORIZON_MONTHS)
                and x["period"] <= edate)
            for r in bank_rows
        )
        # E2: any 4q CET1 decline >= 90th pct before event
        cet1_thr = cet1_q[0.90]
        e2_hit = any(
            compliant(r) and r["period"] < edate and
            (dc := four_q_change(r, "cet1")) is not None and -dc >= cet1_thr
            for r in bank_rows
        )
        # E3: any 4q NPL increase >= 90th pct before event
        npl_thr = npl_q[0.90]
        e3_hit = any(
            compliant(r) and r["period"] < edate and
            (dn := four_q_change(r, "npl")) is not None and dn >= npl_thr
            for r in bank_rows
        )
        flags = []
        if e1_hit: flags.append("E1")
        if e2_hit: flags.append("E2")
        if e3_hit: flags.append("E3")
        cross.append(f"  {eid}: {', '.join(flags) if flags else 'none'}")

    # ----- Print report -----
    print("=" * 70)
    print("T-0 INSTABILITY EVENT COUNTS")
    print("=" * 70)

    for win, label in (("train_val", "TRAIN+VAL (2014-12..2021-12)"),
                       ("test", "TEST (2022-01..2024-12)")):
        s = stats[win]
        print(f"\n{label}")
        print(f"  Total rows         : {s['total']}")
        print(f"  Compliant          : {s['compliant']}")
        print(f"  Non-compliant      : {s['non_compliant']}  (incl. {s['excl_missing']} missing ratio)")
        excl = s['excl_incomplete'] + s['excl_no_future']
        print(f"  Excluded (horizon) : {excl}  ({s['excl_incomplete']} incomplete 2024, {s['excl_no_future']} no future obs)")
        print(f"  E1=1 rows          : {s['e1_pos']}   distinct banks: {len(e1_banks[win])}")
        print(f"  E1=0 rows          : {s['e1_neg']}")

    # 2024 incomplete count
    inc2024 = stats["test"]["excl_incomplete"]
    print(f"\n  2024 rows with incomplete horizon: {inc2024}")

    print("\n--- E1 POSITIVE BANKS ---")
    all_e1 = {}
    all_e1.update(e1_banks["train_val"])
    all_e1.update(e1_banks["test"])
    tv_ids = set(e1_banks["train_val"])
    te_ids = set(e1_banks["test"])
    print(f"{'bank_id':>8}  {'win':>10}  {'first_breach':>12}  {'breach':>30}  name")
    for bid in sorted(all_e1):
        win_tag = ("both" if bid in tv_ids and bid in te_ids
                   else "train_val" if bid in tv_ids else "test")
        info = all_e1[bid]
        print(f"  {bid:>6}  {win_tag:>10}  {info['first_breach']}  {info['breach_detail']:>30}  {info['name']}")

    print("\n--- E1 DECISION ---")
    tv_banks = len(e1_banks["train_val"])
    te_banks = len(e1_banks["test"])
    if tv_banks >= 10 and te_banks >= 5:
        print(f"  E1 PRIMARY  (train+val banks={tv_banks} >= 10, test banks={te_banks} >= 5)")
    else:
        print(f"  FALLBACK TO E2/E3  (train+val banks={tv_banks}, test banks={te_banks})")

    print("\n--- E2/E3 PREVIEW ---")
    print(f"  Quantile base: compliant 2014-12..2019-12; CET1 declines n={len(cet1_declines)}, NPL increases n={len(npl_increases)}")
    print(f"  NPL changes spanning 2020-06 break: {npl_break_count}")
    print(f"\n  {'q':>6}  {'CET1-decline-thr':>18}  {'E2 tv rows':>10}  {'E2 tv banks':>11}  {'E2 te rows':>10}  {'E2 te banks':>11}")
    for q in (0.90, 0.95, 0.975):
        tv = e2_counts.get("train_val", {}).get(q, dict(rows=0, banks=set()))
        te = e2_counts.get("test", {}).get(q, dict(rows=0, banks=set()))
        print(f"  {q:>6.3f}  {cet1_q[q]:>18.4f}  {tv['rows']:>10}  {len(tv['banks']):>11}  {te['rows']:>10}  {len(te['banks']):>11}")
    print(f"\n  {'q':>6}  {'NPL-increase-thr':>18}  {'E3 tv rows':>10}  {'E3 tv banks':>11}  {'E3 te rows':>10}  {'E3 te banks':>11}")
    for q in (0.90, 0.95, 0.975):
        tv = e3_counts.get("train_val", {}).get(q, dict(rows=0, banks=set()))
        te = e3_counts.get("test", {}).get(q, dict(rows=0, banks=set()))
        print(f"  {q:>6.3f}  {npl_q[q]:>18.4f}  {tv['rows']:>10}  {len(tv['banks']):>11}  {te['rows']:>10}  {len(te['banks']):>11}")

    print("\n--- PRIMARY EVENTS CROSS-CHECK ---")
    for line in cross:
        print(line)


if __name__ == "__main__":
    main()
