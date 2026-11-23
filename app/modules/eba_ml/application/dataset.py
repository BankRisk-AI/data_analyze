from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from app.modules.eba_ml.domain.constants import FEATURES, TARGETS


def _months(date_value: date, count: int) -> date:
    absolute = date_value.year * 12 + date_value.month - 1 + count
    year, month = divmod(absolute, 12)
    return date(year, month + 1, date_value.day)


def _approved_ids(conn) -> dict[str, set[int]]:
    with conn.cursor() as cur:
        cur.execute("SELECT bank_id,trim(lei) FROM bank")
        bank_ids = {lei: bank_id for bank_id, lei in cur.fetchall()}
    config = yaml.safe_load(Path("config/bank_crosswalk.yaml").read_text()) or {}
    result: dict[str, set[int]] = {}
    for group in config.get("crosswalks", []):
        if group.get("status") != "approved":
            continue
        ids = {bank_ids[m["lei"]] for m in group.get("members", []) if m["lei"] in bank_ids}
        for member in group.get("members", []):
            result[member["lei"]] = ids
    return result


def _event_ids(conn) -> dict[str, set[int]]:
    with conn.cursor() as cur:
        cur.execute("SELECT bank_id,trim(lei) FROM bank")
        bank_ids = {lei: bank_id for bank_id, lei in cur.fetchall()}
    result = {lei: {bank_id} for lei, bank_id in bank_ids.items()}
    result.update(_approved_ids(conn))
    return result


def _target_rows(rows: list[dict[str, Any]], event_ids: dict, events: list,
                 event_start_months: int = 3) -> dict[str, set[tuple[int, date]]]:
    by_bank: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_bank.setdefault(row["bank_id"], []).append(row)
    result = {target: set() for target in TARGETS}
    for bank_id, bank_rows in by_bank.items():
        bank_rows.sort(key=lambda row: row["period"])
        for row in bank_rows:
            period = row["period"]
            future = [x for x in bank_rows if period < x["period"] <= _months(period, 12)]
            event = any(
                bank_id in event_ids.get(e["bank_lei"].strip(), set())
                and _months(period, event_start_months) <= date.fromisoformat(e["event_date"]) <= _months(period, 12)
                for e in events
            )
            cet1 = row["cet1_ratio"]
            t2 = cet1 is not None and cet1 >= 0.11 and any(
                x["cet1_ratio"] is not None and x["cet1_ratio"] < 0.11 for x in future)
            t3 = cet1 is not None and any(
                x["cet1_ratio"] is not None and cet1 - x["cet1_ratio"] >= 0.03 for x in future)
            t4 = any(x["roe_annualised"] is not None and x["npl_ratio"] is not None
                     and x["roe_annualised"] < 0 and x["npl_ratio"] > 0.08 for x in future)
            t4 = t4 and not (row["roe_annualised"] is not None and row["npl_ratio"] is not None
                             and row["roe_annualised"] < 0 and row["npl_ratio"] > 0.08)
            values = {"T1": event, "T2": t2, "T3": t3, "T4": t4,
                      "T5": event or t2 or t3 or t4, "T5_noT1": t2 or t3 or t4}
            for target, positive in values.items():
                if positive:
                    result[target].add((bank_id, period))
    return result


def build_dataset(conn, grid: str = "semiannual", robustness: bool = False) -> dict[str, Any]:
    if grid not in {"semiannual", "quarterly"}:
        raise ValueError("grid must be semiannual or quarterly")
    with conn.cursor() as cur:
        cur.execute("""SELECT p.bank_id,v.period_end,p.flags,
                              p.cet1_ratio,p.tier1_ratio,p.total_capital_ratio,p.leverage_ratio,
                              p.npl_ratio,p.stage2_share,p.roe_annualised,p.nace_hhi,
                              p.sovereign_hhi,p.loan_growth_qoq,p.loan_growth_yoy
                       FROM panel_row p JOIN dataset_version v USING(version_id)
                       WHERE v.is_active ORDER BY v.period_end,p.bank_id""")
        raw = cur.fetchall()
    rows = []
    for values in raw:
        bank_id, period, flags, *feature_values = values
        if any("specialist_institution" in value for value in (flags or {}).values()):
            continue
        if grid == "semiannual" and period.month not in (6, 12):
            continue
        rows.append({"bank_id": bank_id, "period": period, **dict(zip(FEATURES, feature_values))})
    by_period: dict[date, list[dict[str, Any]]] = {}
    by_bank: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_period.setdefault(row["period"], []).append(row)
        by_bank.setdefault(row["bank_id"], []).append(row)
    active_features = tuple(feature for feature in FEATURES
                            if not (robustness and feature == "loan_growth_qoq"))
    structural = {"stage2_share", "nace_hhi", "leverage_ratio", "loan_growth_qoq",
                  "cet1_ratio", "tier1_ratio", "total_capital_ratio"}
    columns = []
    for feature in active_features:
        columns += [feature, f"{feature}_rank", f"{feature}_change12m"]
        if not (robustness and feature in structural):
            columns.append(f"{feature}_missing")
    matrix = []
    for row in rows:
        values = []
        peers = [x[feature] for x in by_period[row["period"]] if x[feature] is not None]
        for feature in active_features:
            value = row[feature]
            values.append(value)
            values.append(sum(x <= value for x in peers) / len(peers) if value is not None and peers else np.nan)
            previous = next((x[feature] for x in by_bank[row["bank_id"]]
                             if x["period"] == _months(row["period"], -12)), None)
            values.append(value - previous if value is not None and previous is not None else np.nan)
            if not (robustness and feature in structural):
                values.append(0.0 if value is not None else 1.0)
        matrix.append(values)
    catalogue = yaml.safe_load(Path("config/events.yaml").read_text()) or {}
    events = [e for e in catalogue.get("events", [])
              if e.get("set") == "primary" and e.get("status") == "included"]
    event_ids = _event_ids(conn)
    targets = _target_rows(rows, event_ids, events, 3)
    old_targets = _target_rows(rows, event_ids, events, 0)
    panel_hash = hashlib.sha256(json.dumps(
        [(r["bank_id"], r["period"].isoformat(), [r[f] for f in FEATURES]) for r in rows],
        default=str, sort_keys=True).encode()).hexdigest()
    return {"rows": rows, "X": np.asarray(matrix, dtype=float), "columns": columns,
            "targets": targets, "panel_hash": panel_hash, "grid": grid,
            "robustness": robustness,
            "target_counts_before": {name: len(values) for name, values in old_targets.items()},
            "target_counts_after": {name: len(values) for name, values in targets.items()}}


def save_dataset(dataset: dict[str, Any], out_dir: str | Path = "data/ml") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / f"dataset_{dataset['grid']}.npz", X=dataset["X"],
                        **{target: np.asarray([(r["bank_id"], r["period"]) in values
                                               for r in dataset["rows"]])
                           for target, values in dataset["targets"].items()})
    manifest = {"grid": dataset["grid"], "panel_hash": dataset["panel_hash"],
                "rows": len(dataset["rows"]), "columns": dataset["columns"],
                "targets": {k: len(v) for k, v in dataset["targets"].items()}}
    (out / f"manifest_{dataset['grid']}.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return out


def folds(rows: list[dict[str, Any]]) -> list[tuple[np.ndarray, np.ndarray]]:
    result = []
    for test_year in (2017, 2018, 2019, 2020, 2021):
        train = np.asarray([i for i, row in enumerate(rows) if 2014 <= row["period"].year <= test_year - 2])
        test = np.asarray([i for i, row in enumerate(rows) if row["period"].year == test_year])
        result.append((train, test))
    return result
