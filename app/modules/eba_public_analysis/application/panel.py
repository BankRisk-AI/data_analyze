from __future__ import annotations

from psycopg2 import sql

from app.core.exceptions import InvalidParameter, NotFoundError
from app.modules.eba_public_analysis.domain.constants import FEATURES, FLAG_DESCRIPTIONS
from app.modules.eba_public_analysis.infrastructure.db import read_session, specialist_leis, validate_page


def report_types(schema: str) -> list[dict]:
    with read_session(schema) as (_, cur):
        cur.execute("""SELECT report_type, array_agg(DISTINCT file_group ORDER BY file_group)
                       FROM indicator GROUP BY report_type ORDER BY report_type""")
        return [{"name": r[0], "label": r[0], "datasets": list(r[1])} for r in cur.fetchall()]


def report_years(report_type: str, schema: str) -> list[dict]:
    with read_session(schema) as (_, cur):
        cur.execute("""SELECT DISTINCT v.year FROM dataset_version v
                       JOIN indicator i ON i.report_type=%s
                       WHERE v.is_active AND EXISTS (
                         SELECT 1 FROM fact_oth f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_cre f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_mrk f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_sov f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id)
                       ORDER BY v.year""", (report_type,))
        return [{"year": r[0]} for r in cur.fetchall()]


def report_quarters(report_type: str, year: int, schema: str) -> list[dict]:
    with read_session(schema) as (_, cur):
        cur.execute("""SELECT DISTINCT v.period_end, v.quarter FROM dataset_version v
                       JOIN indicator i ON i.report_type=%s
                       WHERE v.is_active AND v.year=%s AND EXISTS (
                         SELECT 1 FROM fact_oth f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_cre f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_mrk f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_sov f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id)
                       ORDER BY v.period_end""", (report_type, year))
        return [{"period": r[0].strftime("%Y%m"), "quarter": f"Q{r[1]}", "reporting_date": r[0].isoformat()} for r in cur.fetchall()]


def banks(schema: str, page: int, page_size: int, country: str | None = None, search: str | None = None) -> dict:
    validate_page(page, page_size)
    specialist = specialist_leis()
    clauses, params = [], []
    if country:
        clauses.append("b.country_code=%s"); params.append(country.upper())
    if search:
        clauses.append("(b.name ILIKE %s OR b.lei ILIKE %s)"); params.extend([f"%{search}%", f"%{search}%"])
    where = " AND ".join(clauses) or "TRUE"
    with read_session(schema) as (_, cur):
        cur.execute(f"""SELECT count(*) FROM bank b WHERE {where}""", params)
        total = cur.fetchone()[0]
        cur.execute(f"""SELECT b.bank_id,trim(b.lei),b.name,b.country_code,min(v.period_end),
                               max(v.period_end),count(DISTINCT v.version_id)
                        FROM bank b LEFT JOIN panel_row p ON p.bank_id=b.bank_id
                        LEFT JOIN dataset_version v ON v.version_id=p.version_id AND v.is_active
                        WHERE {where} GROUP BY b.bank_id ORDER BY b.name,b.bank_id
                        LIMIT %s OFFSET %s""", (*params, page_size, (page - 1) * page_size))
        rows = [{"bank_id": r[0], "lei": r[1], "name": r[2], "country": r[3],
                 "first_period": r[4].strftime("%Y%m") if r[4] else None,
                 "last_period": r[5].strftime("%Y%m") if r[5] else None,
                 "periods": r[6], "specialist_institution": r[1] in specialist} for r in cur.fetchall()]
        return {"rows": rows, "total": total, "page": page, "page_size": page_size}


def bank_panel(bank_id: int, schema: str) -> dict:
    with read_session(schema) as (_, cur):
        cur.execute("""SELECT 1 FROM bank WHERE bank_id=%s""", (bank_id,))
        if not cur.fetchone():
            raise NotFoundError(f"bank {bank_id} does not exist")
        cur.execute("""SELECT to_char(v.period_end,'YYYYMM'),v.period_end,p.cet1_ratio,p.tier1_ratio,
                              p.total_capital_ratio,p.leverage_ratio,p.npl_ratio,p.stage2_share,
                              p.roe_annualised,p.loan_growth_qoq,p.loan_growth_yoy,p.nace_hhi,
                              p.sovereign_hhi,p.npl_delta_qoq,p.cet1_delta_qoq,p.min_headroom,p.flags
                       FROM panel_row p JOIN dataset_version v USING(version_id)
                       WHERE p.bank_id=%s AND v.is_active ORDER BY v.period_end""", (bank_id,))
        columns = ["period", "reporting_date", *FEATURES, "npl_delta_qoq",
                   "cet1_delta_qoq", "min_headroom"]
        periods = []
        for r in cur.fetchall():
            flags = r[-1] or {}
            item = dict(zip(columns, r[:-1]))
            item["flags"] = flags
            item["frequency"] = flags.get("frequency")
            periods.append(item)
        return {"bank_id": bank_id, "periods": periods}


def cross_section(period: str, feature: str, schema: str, exclude_specialist: bool = False) -> dict:
    if feature not in FEATURES or len(period) != 6 or not period.isdigit():
        raise InvalidParameter("feature or period is invalid")
    specialist = specialist_leis()
    with read_session(schema) as (_, cur):
        cur.execute("""SELECT v.version_id FROM dataset_version v
                       WHERE v.is_active AND to_char(v.period_end,'YYYYMM')=%s""", (period,))
        version = cur.fetchone()
        if not version:
            raise NotFoundError(f"active period {period} does not exist")
        cur.execute("""SELECT p.bank_id,trim(b.lei),b.name,p.flags
                       FROM panel_row p JOIN bank b USING(bank_id)
                       WHERE p.version_id=%s ORDER BY b.name""", (version[0],))
        values = []
        for bank_id, lei, name, flags in cur.fetchall():
            if exclude_specialist and lei in specialist:
                continue
            values.append({"bank_id": bank_id, "lei": lei, "name": name,
                           "value": flags.get(feature) if False else None,
                           "flags": (flags or {}).get(feature, [])})
        # The feature identifier is fixed in SQL to avoid dynamic identifiers.
        cur.execute(sql.SQL("SELECT p.bank_id,{} FROM panel_row p WHERE p.version_id=%s").format(sql.Identifier(feature)), (version[0],))
        by_bank = dict(cur.fetchall())
        for item in values:
            item["value"] = by_bank.get(item["bank_id"])
        return {"period": period, "feature": feature, "values": values}


def feature_definitions() -> dict:
    return {"features": [{"name": n, "label": v[0], "formula": v[1], "unit": v[2],
                          "first_period": v[3], "risk_direction": v[4]} for n, v in FEATURES.items()],
            "flags": FLAG_DESCRIPTIONS}


def indicator_series(indicator_id: int, bank_id: int, schema: str) -> dict:
    with read_session(schema) as (_, cur):
        cur.execute("SELECT std_code FROM indicator WHERE indicator_id=%s", (indicator_id,))
        if not cur.fetchone():
            raise NotFoundError(f"indicator {indicator_id} does not exist")
        cur.execute("SELECT 1 FROM bank WHERE bank_id=%s", (bank_id,))
        if not cur.fetchone():
            raise NotFoundError(f"bank {bank_id} does not exist")
        rows = []
        for table, dimensions in (("fact_oth", "jsonb_build_object('assets_fv',f.assets_fv,'assets_stages',f.assets_stages,'exposure',f.exposure,'financial_instruments',f.financial_instruments)"),
                                  ("fact_cre", "jsonb_build_object('portfolio',f.portfolio,'country',f.country,'country_rank',f.country_rank,'exposure',f.exposure,'status',f.status,'perf_status',f.perf_status,'nace_codes',f.nace_codes)"),
                                  ("fact_mrk", "jsonb_build_object('portfolio',f.portfolio,'mkt_modprod',f.mkt_modprod,'mkt_risk',f.mkt_risk)"),
                                  ("fact_sov", "jsonb_build_object('country',f.country,'accounting_portfolio',f.accounting_portfolio,'maturity',f.maturity)")):
            cur.execute(sql.SQL("""SELECT to_char(v.period_end,'YYYYMM'),f.amount,%s,coalesce(m.source_item,''),
                                         {} FROM {} f JOIN dataset_version v USING(version_id)
                                         LEFT JOIN indicator_code_map m ON m.indicator_id=f.indicator_id
                                           AND m.edition_label=(SELECT edition_label FROM import_batch WHERE import_id=v.import_id)
                                         WHERE f.indicator_id=%s AND f.bank_id=%s AND v.is_active
                                         ORDER BY v.period_end""").format(sql.SQL(dimensions), sql.Identifier(table)),
                        (table, indicator_id, bank_id))
            rows.extend({"period": r[0], "value": r[1], "dataset": r[2], "source_code": r[3], "dimensions": r[4]} for r in cur.fetchall())
        rows.sort(key=lambda r: r["period"])
        return {"indicator_id": indicator_id, "bank_id": bank_id, "rows": rows}
