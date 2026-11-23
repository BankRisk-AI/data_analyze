"""The inner load logic: reference file parsing and fact table population.
Called by run_load() inside the transaction it owns."""
from __future__ import annotations

import calendar
import re
import time
from collections import Counter, defaultdict
from datetime import date

from openpyxl import load_workbook
from psycopg2 import sql
from psycopg2.extras import Json

from app.core.data_decisions import DataDecision, load_data_decisions
from app.core.preflight import collision_check
from app.modules.eba_ingest.domain.exceptions import LoadError
from app.shared.staging import staging_identifier
from app.shared.sql.predicates import NUMBER_REGEX, aggregate_rows_predicate, blank_text, numeric_amount


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _workbook_rows(path: str, sheet: str | None = None):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        yield from ([("" if v is None else str(int(v) if isinstance(v, float) and v.is_integer() else v)) for v in row]
                    for row in ws.iter_rows(values_only=True))
    finally:
        wb.close()


def _header_rows(rows):
    rows = iter(rows)
    for row in rows:
        headers = [_norm(v) for v in row]
        if "item" in headers or "lei_code" in headers:
            return headers, rows
    return [], iter(())


def _reference_files(cur, import_id: int) -> dict[str, str]:
    cur.execute("SELECT file_type, stored_path FROM source_file WHERE import_id = %s", (import_id,))
    return {kind: path for kind, path in cur.fetchall() if kind in {"SDD", "TR_Metadata"}}


def _decision_condition(decision: DataDecision, columns: list[str], cur):
    values = {"lei_code": decision.lei, "period": decision.period, "item": decision.item, **decision.dimensions}
    parts, params = [], []
    for column, value in values.items():
        if column not in columns:
            raise LoadError(f"data decision {decision.id} references missing column {column}")
        parts.append(sql.SQL("btrim({}) = %s").format(sql.Identifier(column)))
        params.append(value)
    if decision.action == "keep_amount":
        if "amount" not in columns or decision.amount is None:
            raise LoadError(f"data decision {decision.id} requires an amount")
        parts.append(sql.SQL("btrim(amount) = %s").format(sql.Identifier("amount")))
        params.append(decision.amount)
    return sql.SQL(" AND ").join(parts), params


def _sdd(path: str, edition: str | None, file_groups: set[str]):
    headers, rows = _header_rows(_workbook_rows(path))
    if not headers:
        raise LoadError("SDD has no Item header")
    item_idx = headers.index("item")
    label_idx = headers.index("label") if "label" in headers else None
    category_idx = headers.index("category") if "category" in headers else None
    dataset_idx = headers.index("dataset") if "dataset" in headers else None
    edition_col = next((i for i, h in enumerate(headers) if h == f"item_tr_{(edition or '').lower()}"), None)
    mapping: dict[str, dict] = {}
    labels: dict[tuple[str, str], str] = {}
    for row in rows:
        row = list(row) + [""] * max(0, len(headers) - len(row))
        std = row[item_idx].strip()
        if not std:
            continue
        label = row[label_idx].strip() if label_idx is not None else std
        group = _norm(row[dataset_idx]).replace("tr_", "") if dataset_idx is not None else ""
        category = row[category_idx].strip() if category_idx is not None else "Unclassified"
        mapping[std] = {"std_code": std, "label": label, "group": group, "category": category}
        labels[(group, label)] = std
        if edition_col is not None and row[edition_col].strip():
            mapping.setdefault(row[edition_col].strip(), mapping[std])
    return mapping, labels


def _metadata(path: str):
    if not path:
        return []
    from app.modules.eba_ingest.infrastructure.readers.readers import xlsx_bank_list_sheet

    sheet = xlsx_bank_list_sheet(path)
    if sheet is None:
        return []
    rows = list(_workbook_rows(path, sheet))
    header_at = next((i for i, r in enumerate(rows) if "lei_code" in [_norm(x) for x in r]), None)
    if header_at is None:
        return []
    headers = [_norm(x) for x in rows[header_at]]
    out = []
    for row in rows[header_at + 1:]:
        values = list(row) + [""] * max(0, len(headers) - len(row))
        record = dict(zip(headers, values))
        lei = record.get("lei_code", "").strip()
        if not lei:
            continue
        previous = {record[k].strip() for k in headers if k.startswith("lei_code_") and record.get(k, "").strip()}
        previous.discard(lei)
        out.append((lei, record.get("name") or record.get("bank_name") or None,
                    (record.get("country") or record.get("country_code") or "")[:2] or None,
                    str(record.get("finrep", "")).lower().startswith("yes"), sorted(previous)))
    return out


def _load(cur, import_id: int, emit):
    timings: dict[str, float] = {}
    phase_started = time.perf_counter()
    cur.execute("SELECT status, edition_label, created_by FROM import_batch WHERE import_id = %s FOR UPDATE", (import_id,))
    head = cur.fetchone()
    if not head:
        raise LoadError(f"import {import_id} does not exist")
    if head[0] not in ("validated", "failed", "approved", "loading"):
        raise LoadError(f"import {import_id} is not ready for load: {head[0]}")
    cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'load_request',%s)",
                (import_id, Json({"edition": head[1]})))
    cur.execute("SELECT file_id, file_type, file_name FROM source_file WHERE import_id = %s ORDER BY file_id", (import_id,))
    files = cur.fetchall()
    data = [(fid, typ, name) for fid, typ, name in files if typ in {"tr_oth", "tr_cre", "tr_mrk", "tr_sov"}]
    if not data:
        raise LoadError("no recognised EBA data files")
    paths = _reference_files(cur, import_id)
    cur.execute("SELECT file_type, sha256 FROM source_file WHERE import_id=%s", (import_id,))
    source_hashes = dict(cur.fetchall())
    timings["reference_files"] = round(time.perf_counter() - phase_started, 2)
    phase_started = time.perf_counter()
    target_tables = {"tr_oth": "fact_oth", "tr_cre": "fact_cre", "tr_mrk": "fact_mrk", "tr_sov": "fact_sov"}
    source_only = {"lei_code", "nsa", "period", "item", "label"}
    source_column_map = {"row": "source_row", "column": "source_column", "sheet": "source_sheet"}
    target_columns: dict[str, list[str]] = {}
    staging_columns: dict[int, list[str]] = {}
    decision_exclusions: dict[int, list[tuple[sql.Composable, list]]] = defaultdict(list)
    applied_decisions: list[tuple[str, int]] = []
    for fid, typ, name in data:
        table = staging_identifier(fid)
        cur.execute(sql.SQL("SELECT * FROM {} LIMIT 0").format(table))
        columns = [d[0] for d in cur.description]
        staging_columns[fid] = columns
        cur.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = %s
               ORDER BY ordinal_position""",
            (target_tables[typ],),
        )
        target_columns[typ] = [r[0] for r in cur.fetchall()]
        unknown = [c for c in columns if c not in source_only and c not in source_column_map and c not in target_columns[typ]]
        if unknown:
            raise LoadError(f"schema-mismatch: {', '.join(unknown)}")
    edition = str(head[1] or "").strip()
    for decision in load_data_decisions():
        matching = [(fid, typ) for fid, typ, _ in data if typ == decision.file_type]
        if not matching:
            continue
        for fid, _ in matching:
            required = {"lei_code", "period", "item", *decision.dimensions}
            if not required.issubset(staging_columns[fid]):
                continue
            condition, params = _decision_condition(decision, staging_columns[fid], cur)
            table = staging_identifier(fid)
            cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE ").format(table) + condition, params)
            count = cur.fetchone()[0]
            if count == 0:
                continue
            expected = 2 if decision.action == "exclude" else 1
            if count != expected:
                raise LoadError(f"data decision {decision.id} matched {count} rows; expected {expected}")
            if decision.action == "exclude":
                decision_exclusions[fid].append((condition, params))
                applied_decisions.append((decision.id, count))
            else:
                raise LoadError(f"data decision action {decision.action} is not implemented")

    collisions = collision_check(cur, import_id)
    if collisions:
        counts = Counter(row["class"] for row in collisions)
        detail = ", ".join(f"class {key}={value}" for key, value in sorted(counts.items()))
        tables = ", ".join(sorted({row["fact_table"] for row in collisions}))
        raise LoadError(f"preflight-collisions: {detail}; duplicate-facts: {tables}; no facts inserted")

    emit("resolving banks and indicators", 10)
    for lei, name, country, finrep, previous in _metadata(paths.get("TR_Metadata", "")):
        cur.execute(
            """SELECT bank_id FROM bank
               WHERE lei = ANY(%s) ORDER BY bank_id LIMIT 1
               FOR UPDATE""",
            (previous,),
        )
        predecessor = cur.fetchone()
        if predecessor:
            cur.execute(
                """UPDATE bank
                   SET previous_leis = (
                       SELECT ARRAY(SELECT DISTINCT value FROM unnest(
                           COALESCE(previous_leis, ARRAY[]::text[]) || %s || ARRAY[%s]
                       ) AS value ORDER BY value)
                   )
                   WHERE bank_id=%s""",
                (previous, lei, predecessor[0]),
            )
            continue
        cur.execute("""INSERT INTO bank(lei,name,country_code,finrep_reported,previous_leis)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (lei) DO UPDATE SET name=EXCLUDED.name,country_code=EXCLUDED.country_code,
                       finrep_reported=EXCLUDED.finrep_reported,previous_leis=EXCLUDED.previous_leis""",
                    (lei, name, country, finrep, previous))
    cur.execute("""
        CREATE TEMP TABLE tmp_load_versions (
            year integer NOT NULL, quarter integer NOT NULL, version_id integer NOT NULL,
            PRIMARY KEY (year, quarter)
        ) ON COMMIT DROP
    """)
    cur.execute("""
        CREATE TEMP TABLE tmp_load_banks (
            lei text PRIMARY KEY, bank_id integer NOT NULL
        ) ON COMMIT DROP
    """)
    cur.execute("""
        CREATE TEMP TABLE tmp_load_items (
            file_group text NOT NULL, item text NOT NULL, label text NOT NULL,
            indicator_id integer NOT NULL, PRIMARY KEY (file_group, item, label)
        ) ON COMMIT DROP
    """)
    non_aggregate = aggregate_rows_predicate()
    for fid, typ, _ in data:
        table = staging_identifier(fid)
        exclusions = decision_exclusions.get(fid, [])
        if not exclusions:
            for decision in load_data_decisions():
                if decision.file_type != typ:
                    continue
                required = {"lei_code", "period", "item", *decision.dimensions}
                if not required.issubset(staging_columns[fid]):
                    continue
                condition, params = _decision_condition(decision, staging_columns[fid], cur)
                cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE ").format(table) + condition, params)
                if cur.fetchone()[0] == 2 and decision.action == "exclude":
                    exclusions.append((condition, params))
        exclusion_sql = sql.SQL("")
        exclusion_params = []
        if exclusions:
            exclusion_sql = sql.SQL(" AND NOT (") + sql.SQL(" OR ").join(
                sql.SQL("(") + condition + sql.SQL(")") for condition, _ in exclusions
            ) + sql.SQL(")")
            exclusion_params = [value for _, params in exclusions for value in params]
        cur.execute(sql.SQL("""
            WITH source_leis AS (
                SELECT DISTINCT btrim(s.lei_code) AS lei
                FROM {} s
                WHERE NOT {} AND btrim(s.lei_code) <> ''
            )
            INSERT INTO bank(lei)
            SELECT l.lei
            FROM source_leis l
            WHERE NOT EXISTS (
                  SELECT 1 FROM bank b
                  WHERE btrim(b.lei) = l.lei
                     OR EXISTS (SELECT 1 FROM unnest(b.previous_leis) p
                                WHERE btrim(p) = l.lei)
              )
            ON CONFLICT (lei) DO NOTHING
        """).format(table, sql.SQL(non_aggregate)))
        cur.execute(sql.SQL("""
            WITH source_leis AS (
                SELECT DISTINCT btrim(s.lei_code) AS lei
                FROM {} s
                WHERE NOT {}
            )
            INSERT INTO tmp_load_banks(lei, bank_id)
            SELECT l.lei, b.bank_id
            FROM source_leis l
            JOIN bank b ON btrim(b.lei) = l.lei
                OR EXISTS (SELECT 1 FROM unnest(b.previous_leis) p
                           WHERE btrim(p) = l.lei)
            ON CONFLICT (lei) DO NOTHING
        """).format(table, sql.SQL(non_aggregate)))
    timings["bank_resolution"] = round(time.perf_counter() - phase_started, 2)
    phase_started = time.perf_counter()

    indicator_cache = {}
    cur.execute("SELECT indicator_id, std_code FROM indicator")
    indicator_cache.update({code: indicator_id for indicator_id, code in cur.fetchall()})
    versions = {}
    resolution = Counter()
    quality = defaultdict(lambda: {"files": [], "rows_staged": 0, "aggregate_rows_excluded": 0,
                                   "rows_loaded": 0, "amount_sum": 0.0})
    for fid, typ, name in data:
        table = staging_identifier(fid)
        cur.execute(sql.SQL("SELECT DISTINCT btrim(period) FROM {} WHERE NOT {}").format(table, sql.SQL(non_aggregate)))
        periods = [row[0] or "" for row in cur.fetchall()]
        for period in periods:
            if not re.fullmatch(r"\d{6}", period):
                raise LoadError(f"invalid period in {name}")
            year, month = int(period[:4]), int(period[4:])
            quarter = (month - 1) // 3 + 1
            key = (year, quarter)
            if key not in versions:
                emit(f"creating version {year} Q{quarter}", 25)
                cur.execute("SELECT version_id FROM dataset_version WHERE year=%s AND quarter=%s AND is_active FOR UPDATE", key)
                old = cur.fetchone()
                if old:
                    cur.execute("UPDATE dataset_version SET is_active=false WHERE version_id=%s", old)
                cur.execute("SELECT COALESCE(max(version_no),0)+1 FROM dataset_version WHERE year=%s AND quarter=%s", key)
                version_no = cur.fetchone()[0]
                cur.execute("""INSERT INTO dataset_version(year,quarter,period_end,import_id,version_no,is_active,quality)
                               VALUES (%s,%s,%s,%s,%s,true,%s) RETURNING version_id""",
                            (year, quarter, date(year, month, calendar.monthrange(year, month)[1]), import_id, version_no, Json({"validation": {}, "files": []})))
                versions[key] = cur.fetchone()[0]
        if versions:
            cur.execute("INSERT INTO tmp_load_versions(year,quarter,version_id) VALUES " +
                        ",".join(["(%s,%s,%s)"] * len(versions)) + " ON CONFLICT DO NOTHING",
                        [value for key, value in versions.items() for value in (key[0], key[1], value)])

        group = typ.replace("tr_", "")
        label_expr = sql.SQL("btrim(label)") if "label" in staging_columns[fid] else sql.SQL("NULL")
        cur.execute(sql.SQL("SELECT btrim(item), coalesce({}, ''), count(*) FROM {} WHERE NOT {} GROUP BY 1,2")
                    .format(label_expr, table, sql.SQL(non_aggregate)))
        for item, label, count in cur.fetchall():
            item, label = item or "", label or ""
            cur.execute("""SELECT indicator_id, method
                           FROM indicator_code_map
                           WHERE edition_label=%s AND dataset=%s AND source_item=%s""",
                        (edition, group, item))
            mapped = cur.fetchone()
            if mapped and mapped[0] is None:
                raise LoadError(f"ambiguous item mapping: {edition}/{group}/{item}")
            if mapped:
                indicator, method = mapped
                resolution[method] += count
            else:
                method = "unmapped"
                std = item
                indicator = indicator_cache.get(std)
                if indicator is None:
                    cur.execute("""INSERT INTO indicator(std_code,label,report_type,file_group,aggregation_rule,
                                   first_seen_edition,last_seen_edition)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                                   ON CONFLICT (std_code) DO UPDATE SET label=EXCLUDED.label
                                   RETURNING indicator_id""",
                                (std, label or item, "Unclassified", group, "stock", edition, edition))
                    row = cur.fetchone()
                    if row is None:
                        cur.execute("SELECT indicator_id FROM indicator WHERE std_code=%s", (std,))
                        row = cur.fetchone()
                    indicator = row[0]
                    indicator_cache[std] = indicator
                cur.execute("""INSERT INTO indicator_code_map
                               (edition_label,dataset,source_item,source_label,indicator_id,method,sdd_file_sha256)
                               VALUES (%s,%s,%s,%s,%s,'unmapped',%s)
                               ON CONFLICT (edition_label,dataset,source_item) DO NOTHING""",
                            (edition, group, item, label, indicator, source_hashes.get("SDD")))
                resolution[method] += count
            cur.execute("INSERT INTO tmp_load_items(file_group,item,label,indicator_id) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (group, item, label, indicator))

        columns = staging_columns[fid]
        allowed = [(source_column_map.get(c, c), c) for c in columns
                   if source_column_map.get(c, c) in target_columns[typ]]
        fields = ["version_id", "bank_id", "indicator_id"] + [target for target, _ in allowed]
        expressions = ["tv.version_id", "tb.bank_id", "ti.indicator_id"]
        for column, source in allowed:
            quoted = sql.Identifier(source).as_string(cur)
            if column == "amount":
                expressions.append(numeric_amount(quoted))
            elif column == "n_quarters":
                expressions.append(f"CASE WHEN {quoted} ~ '^[+-]?\\d+$' THEN {quoted}::smallint END")
            else:
                expressions.append(blank_text(quoted))
        quarter_expr = "((substring(btrim(s.period), 5, 2)::integer - 1) / 3 + 1)"
        duplicate_ignored = {"label", "footnote", "row", "column", "sheet",
                             "source_row", "source_column", "source_sheet"}
        duplicate_key = [c for c in columns if c not in duplicate_ignored]
        conflict_key = [c for c in duplicate_key if c != "amount"]
        conflict_columns = sql.SQL(", ").join(sql.Identifier(c) for c in conflict_key)
        if "amount" in columns and conflict_key and typ != "tr_cre":
            cur.execute(sql.SQL("""
                SELECT count(*) FROM (
                    SELECT {}
                    FROM {}
                    WHERE NOT {} {}
                    GROUP BY {}
                    HAVING count(DISTINCT CASE WHEN btrim(amount) ~ %s
                                               THEN btrim(amount)::numeric::text
                                               ELSE btrim(amount) END) > 1
                ) conflicts
            """).format(conflict_columns, table, sql.SQL(non_aggregate),
                        exclusion_sql, conflict_columns),
                        [*exclusion_params, NUMBER_REGEX])
            conflict_count = cur.fetchone()[0]
            if conflict_count:
                raise LoadError(f"duplicate-facts: {target_tables[typ]}")
        duplicate_columns = sql.SQL(", ").join(sql.Identifier(c) for c in duplicate_key)
        duplicate_order = sql.SQL(", ").join(
            sql.SQL(f"CASE WHEN btrim(s.amount) ~ '{NUMBER_REGEX}' THEN btrim(s.amount)::numeric::text ELSE btrim(s.amount) END")
            if c == "amount" else sql.SQL("btrim(s.{})").format(sql.Identifier(c))
            for c in duplicate_key
        )
        source = sql.SQL("(SELECT DISTINCT ON ({}) s.* FROM {} s ORDER BY {}, s.ctid) s").format(
            duplicate_order, table, duplicate_order
        )
        cur.execute(sql.SQL("SELECT count(*), coalesce(sum(amount), 0) FROM {} WHERE version_id IN ({})").format(
            sql.Identifier(target_tables[typ]),
            sql.SQL(", ").join(sql.Placeholder() for _ in versions),
        ), tuple(versions.values()))
        prior_loaded, prior_amount = cur.fetchone()
        cur.execute("SET LOCAL enable_nestloop = off")
        cur.execute(sql.SQL("""
            INSERT INTO {} ({})
            SELECT {}
            FROM {}
            JOIN tmp_load_versions tv
              ON tv.year = substring(btrim(s.period), 1, 4)::integer
             AND tv.quarter = {}
            JOIN tmp_load_banks tb ON tb.lei = btrim(s.lei_code)
            JOIN tmp_load_items ti
              ON ti.file_group = {}
             AND ti.item = coalesce(btrim(s.item), '')
             AND ti.label = coalesce({}, '')
            WHERE NOT {}
            ON CONFLICT DO NOTHING
        """).format(sql.Identifier(target_tables[typ]),
                    sql.SQL(", ").join(map(sql.Identifier, fields)),
                    sql.SQL(", ").join(sql.SQL(expression) for expression in expressions),
                    source, sql.SQL(quarter_expr), sql.Literal(group),
                    sql.SQL("btrim(s.label)") if "label" in staging_columns[fid] else sql.SQL("NULL"),
                    sql.SQL(non_aggregate), exclusion_sql), exclusion_params)
        emit(f"loaded {name}", 70)
        cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE version_id IN ({})").format(
            sql.Identifier(target_tables[typ]),
            sql.SQL(", ").join(sql.Placeholder() for _ in versions),
        ), tuple(versions.values()))
        loaded = cur.fetchone()[0] - prior_loaded
        cur.execute(sql.SQL("SELECT coalesce(sum(amount), 0) FROM {} WHERE version_id IN ({})").format(
            sql.Identifier(target_tables[typ]),
            sql.SQL(", ").join(sql.Placeholder() for _ in versions),
        ), tuple(versions.values()))
        amount_sum = cur.fetchone()[0] - prior_amount
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(table))
        staged = cur.fetchone()[0]
        quality[typ]["files"].append(name)
        quality[typ]["rows_staged"] += staged
        quality[typ]["aggregate_rows_excluded"] += staged - loaded
        quality[typ]["rows_loaded"] += loaded
        quality[typ]["amount_sum"] += float(amount_sum)
    timings["fact_inserts"] = round(time.perf_counter() - phase_started, 2)
    phase_started = time.perf_counter()
    for key, version_id in versions.items():
        cur.execute("UPDATE dataset_version SET quality=%s WHERE version_id=%s", (Json({"validation": {}, "files": list(quality.values())}), version_id))
    for typ, report in quality.items():
        view = {"tr_oth": "v_tr_oth", "tr_cre": "v_tr_cre", "tr_mrk": "v_tr_mrk", "tr_sov": "v_tr_sov"}[typ]
        cur.execute(f"SELECT count(*), coalesce(sum(amount),0), count(*) FILTER (WHERE amount IS NULL) FROM {view} v JOIN dataset_version d USING (version_id) WHERE d.import_id=%s", (import_id,))
        actual_rows, actual_sum, actual_empty = cur.fetchone()
        tolerance = max(1e-6, abs(report["amount_sum"]) * 1e-12)
        if actual_rows != report["rows_loaded"] or abs(float(actual_sum) - report["amount_sum"]) > tolerance:
            raise LoadError(f"load-mismatch in {report['file']}")
    timings["post_checks"] = round(time.perf_counter() - phase_started, 2)
    cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'item_resolution',%s)", (import_id, Json({"counts": dict(resolution)})))
    for decision_id, rows_affected in applied_decisions:
        cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'data_decision',%s)",
                    (import_id, Json({"id": decision_id, "rows_affected": rows_affected})))
    cur.execute("UPDATE import_batch SET status='loaded' WHERE import_id=%s", (import_id,))
    return list(versions.values()), timings
