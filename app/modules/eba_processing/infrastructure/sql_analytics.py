"""SQL behind preview, item catalogue, column profile, null analysis, histogram and scatter. All of it reads the staging tables."""
from __future__ import annotations

import math

from psycopg2 import sql

from app.core.exceptions import InvalidParameter
from app.modules.eba_processing.domain import DEFAULT_BINS, TOP_VALUES_MAX_DISTINCT, Filters, column_role
from app.modules.eba_processing.domain.binning import clip_bounds, make_edges, transform_bounds
from app.modules.eba_processing.infrastructure.datasets import Dataset
from app.modules.eba_processing.infrastructure.sql_filters import clause, conditions, where
from app.shared.sql.predicates import NUMBER_REGEX, aggregate_rows_predicate, blank_text, numeric_amount

NUM = numeric_amount("amount")
BLANK_AMOUNT = blank_text("amount")


def _one(cur, query, params=()):
    cur.execute(query, params)
    return cur.fetchone()


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ---- preview ----------------------------------------------------------------------------------------------
def preview(cur, ds: Dataset, f: Filters, page: int, page_size: int, sort: str | None, order: str) -> dict:
    w, params = where(ds, f)
    total = _one(cur, sql.SQL("SELECT count(*) FROM {}").format(ds.table) + w, params)[0]
    if sort is None:
        order_by = sql.SQL("ORDER BY ctid")
    elif sort == "amount":
        order_by = sql.SQL("ORDER BY " + NUM + " " + ("DESC" if order == "desc" else "ASC") + " NULLS LAST, ctid")
    else:
        order_by = sql.SQL("ORDER BY {} " + ("DESC" if order == "desc" else "ASC") + " NULLS LAST, ctid").format(ds.col(sort))
    cur.execute(sql.SQL("SELECT {} FROM {}").format(sql.SQL(", ").join(sql.Identifier(c) for c in ds.columns), ds.table) + w + sql.SQL(" ") + order_by + sql.SQL(" LIMIT %s OFFSET %s"),
                params + [page_size, (page - 1) * page_size])
    names = [d[0] for d in cur.description]
    return {"total": total, "rows": [dict(zip(names, r)) for r in cur.fetchall()]}


# ---- item catalogue -----------------------------------------------------------------------------------------
def items(cur, ds: Dataset, f: Filters, q: str | None, page: int, page_size: int) -> dict:
    conds, params = conditions(ds, f)
    extra = []
    if q:
        extra.append("(item ILIKE %s OR label ILIKE %s)")
        params = params + [_like(q), _like(q)]
    base = sql.SQL("FROM {}").format(ds.table) + clause(conds, *extra)
    total = _one(cur, sql.SQL("SELECT count(DISTINCT item) ") + base, params)[0]
    cur.execute(
        sql.SQL(f"""SELECT item, max(label), count(*), count(DISTINCT lei_code),
                          count(*) FILTER (WHERE {BLANK_AMOUNT} IS NULL),
                          count(*) FILTER (WHERE {BLANK_AMOUNT} IS NOT NULL AND amount !~ '{NUMBER_REGEX}'),
                          count(DISTINCT label) """) + base + sql.SQL(" GROUP BY item ORDER BY item LIMIT %s OFFSET %s"),
        params + [page_size, (page - 1) * page_size],
    )
    keys = ["item", "label", "rows", "banks", "null_amount", "non_numeric_amount", "labels"]
    return {"total": total, "items": [dict(zip(keys, r)) for r in cur.fetchall()]}


def periods(cur, ds: Dataset) -> tuple[int, list[dict]]:
    """Total rows and the periods with their banks and rows (aggregate bucket excluded)."""
    total = _one(cur, sql.SQL("SELECT count(*) FROM {}").format(ds.table))[0]
    cur.execute(sql.SQL("SELECT period, count(DISTINCT lei_code), count(*) FROM {} WHERE NOT " + aggregate_rows_predicate() + " AND period ~ '^[0-9]{{6}}$' GROUP BY period ORDER BY period").format(ds.table))
    out = []
    for period, banks, rows in cur.fetchall():
        month = int(period[4:6])
        out.append({"period": period, "year": int(period[:4]), "quarter": (month - 1) // 3 + 1 if 1 <= month <= 12 else 0, "banks": banks, "rows": rows})
    return total, out


# ---- profile and nulls --------------------------------------------------------------------------------------
def profile(cur, ds: Dataset, f: Filters, with_distinct: bool, top: int) -> dict:
    w, params = where(ds, f)
    exprs, order = [sql.SQL("count(*)")], []
    for c in ds.columns:
        col = sql.Identifier(c)
        exprs.append(sql.SQL("count(*) FILTER (WHERE NULLIF(btrim({c}), '') IS NULL)").format(c=col))
        exprs.append(sql.SQL("min(length({c}))").format(c=col))
        exprs.append(sql.SQL("max(length({c}))").format(c=col))
        exprs.append(sql.SQL("count(DISTINCT {c})").format(c=col) if with_distinct else sql.SQL("NULL::bigint"))
        order.append(c)
    row = _one(cur, sql.SQL("SELECT ") + sql.SQL(", ").join(exprs) + sql.SQL(" FROM {}").format(ds.table) + w, params)
    total = row[0]
    cols = []
    for i, c in enumerate(order):
        nulls, mn, mx, distinct = row[1 + i * 4: 5 + i * 4]
        top_values: list[dict] = []
        if top > 0 and distinct is not None and 0 < distinct <= TOP_VALUES_MAX_DISTINCT and c != "amount":
            cur.execute(sql.SQL("SELECT NULLIF(btrim({c}), ''), count(*) FROM {t}").format(c=sql.Identifier(c), t=ds.table) + w
                        + sql.SQL(" GROUP BY 1 ORDER BY 2 DESC, 1 NULLS LAST LIMIT %s"), params + [top])
            top_values = [{"value": v, "count": n} for v, n in cur.fetchall()]
        cols.append({"name": c, "role": column_role(c), "non_null": total - nulls, "nulls": nulls, "null_pct": round(100 * nulls / total, 4) if total else 0.0,
                     "distinct": distinct, "min_length": mn, "max_length": mx, "top_values": top_values})
    a = _one(cur, sql.SQL(f"SELECT count({NUM}), count(*) FILTER (WHERE {BLANK_AMOUNT} IS NOT NULL AND {NUM} IS NULL), min({NUM}), max({NUM}), avg({NUM}) FROM {{}}").format(ds.table) + w, params)
    return {"rows": total, "columns": cols, "amount": {"numeric": a[0], "non_numeric": a[1], "min": a[2], "max": a[3], "mean": a[4]}}


def nulls_by_period(cur, ds: Dataset, f: Filters, columns: list[str]) -> dict:
    cols = columns or ds.columns
    for c in cols:
        ds.col(c)
    w, params = where(ds, f)
    exprs = [sql.SQL("count(*) FILTER (WHERE NULLIF(btrim({c}), '') IS NULL)").format(c=sql.Identifier(c)) for c in cols]
    cur.execute(sql.SQL("SELECT period, count(*), ") + sql.SQL(", ").join(exprs) + sql.SQL(" FROM {}").format(ds.table) + w + sql.SQL(" GROUP BY period ORDER BY period"), params)
    groups = []
    for r in cur.fetchall():
        rows = r[1]
        groups.append({"group": r[0], "rows": rows, "nulls": dict(zip(cols, r[2:])), "null_pct": {c: round(100 * n / rows, 4) if rows else 0.0 for c, n in zip(cols, r[2:])}})
    return {"by": "period", "columns": cols, "groups": groups}


def nulls_by_item(cur, ds: Dataset, f: Filters, limit: int) -> dict:
    """Items whose amount is empty or not a number in some rows, the worst share first."""
    w, params = where(ds, f)
    bad = f"count(*) FILTER (WHERE {NUM} IS NULL)"              # NUM is NULL for empty and for non-numeric amounts
    cur.execute(
        sql.SQL(f"SELECT item, max(label), count(*), {bad} FROM {{}}").format(ds.table) + w
        + sql.SQL(f" GROUP BY item HAVING {bad} > 0 ORDER BY ({bad})::float / count(*) DESC, item LIMIT %s"),
        params + [limit],
    )
    groups = [{"group": r[0], "label": r[1], "rows": r[2], "nulls": {"amount": r[3]}, "null_pct": {"amount": round(100 * r[3] / r[2], 4)}} for r in cur.fetchall()]
    return {"by": "item", "columns": ["amount"], "groups": groups}


# ---- histogram ----------------------------------------------------------------------------------------------
def histogram(cur, ds: Dataset, f: Filters, bins: int, scale: str, clip: str) -> dict:
    w, params = where(ds, f)
    s = _one(
        cur,
        sql.SQL(f"""SELECT count(*), count(*) FILTER (WHERE {BLANK_AMOUNT} IS NULL),
                           count(*) FILTER (WHERE {BLANK_AMOUNT} IS NOT NULL AND {NUM} IS NULL),
                           count({NUM}), min({NUM}), max({NUM}), avg({NUM}), stddev_samp({NUM}),
                           percentile_cont(ARRAY[0.01, 0.25, 0.5, 0.75, 0.99]) WITHIN GROUP (ORDER BY {NUM})
                    FROM {{}}""").format(ds.table) + w, params)
    total, blank, non_numeric, n, mn, mx, mean, std, pct = s
    result = {"rows": total, "n": n, "nulls": blank, "non_numeric": non_numeric, "scale": scale, "clip": clip, "bins": [], "note": None,
              "stats": None, "range": None, "outside": 0, "non_positive": 0}
    if not n:
        return result
    p01, q1, med, q3, p99 = pct
    result["stats"] = {"min": mn, "p01": p01, "p25": q1, "median": med, "p75": q3, "p99": p99, "max": mx, "mean": mean, "std": std}
    lo, hi, note = clip_bounds(clip, mn, mx, p01, q1, q3, p99)
    conds, params = conditions(ds, f)
    value_cond = f"{NUM} IS NOT NULL"
    if scale == "log":
        positive = _one(cur, sql.SQL(f"SELECT min({NUM}) FILTER (WHERE {NUM} > 0), count(*) FILTER (WHERE {NUM} <= 0) FROM {{}}").format(ds.table) + w, params)
        result["non_positive"] = positive[1]
        if positive[0] is None:
            raise InvalidParameter("a logarithmic scale needs positive values and there are none in this selection")
        lo = max(lo, positive[0])
        hi = max(hi, lo)
        value_cond = f"{NUM} > 0"
    result["range"] = {"lo": lo, "hi": hi}
    result["note"] = note
    drawable = n - result["non_positive"] if scale == "log" else n
    inside = f"{NUM} BETWEEN %s AND %s"
    if lo == hi:
        cnt = _one(cur, sql.SQL("SELECT count(*) FROM {}").format(ds.table) + clause(conds, value_cond, inside), params + [lo, hi])[0]
        result["bins"] = [{"x0": lo, "x1": hi, "count": cnt}]
        result["outside"] = drawable - cnt
        return result
    tl, th = transform_bounds(lo, hi, scale)
    expr = f"log({NUM})" if scale == "log" else NUM
    cur.execute(
        sql.SQL(f"SELECT LEAST(width_bucket({expr}, %s, %s, %s), %s) AS b, count(*) FROM {{}}").format(ds.table) + clause(conds, value_cond, inside) + sql.SQL(" GROUP BY 1 ORDER BY 1"),
        [tl, th, bins, bins] + params + [lo, hi],
    )
    counts = {b: c for b, c in cur.fetchall()}
    edges = make_edges(lo, hi, bins, scale)
    result["bins"] = [{"x0": edges[i], "x1": edges[i + 1], "count": counts.get(i + 1, 0)} for i in range(bins)]
    result["outside"] = drawable - sum(counts.values())
    return result


# ---- scatter ------------------------------------------------------------------------------------------------
_AGG = {"single": "max({v})", "sum": "sum({v})", "mean": "avg({v})", "min": "min({v})", "max": "max({v})"}


def _axis(ds: Dataset, f: Filters, agg: str, name: str) -> tuple[sql.Composable, list]:
    if f.item is None or f.period is None:
        raise InvalidParameter(f"{name}_item and {name}_period are required")
    conds, params = conditions(ds, f)
    return (sql.SQL(f"SELECT lei_code, max(nsa) AS nsa, {_AGG[agg].format(v=NUM)} AS v, count(*) AS n FROM {{}}").format(ds.table)
            + clause(conds, f"{NUM} IS NOT NULL") + sql.SQL(" GROUP BY lei_code"), params)


def scatter(cur, ds: Dataset, fx: Filters, fy: Filters, agg: str, max_points: int) -> dict:
    qx, px = _axis(ds, fx, agg, "x")
    qy, py = _axis(ds, fy, agg, "y")
    if agg == "single":
        for name, q, p in (("x", qx, px), ("y", qy, py)):
            dup = _one(cur, sql.SQL("SELECT count(*) FROM (") + q + sql.SQL(") a WHERE n > 1"), p)[0]
            if dup:
                raise InvalidParameter(f"the {name} item has several rows for {dup} banks (dimension columns); choose agg=sum|mean|min|max or narrow it with {name}_dim=column:value")
    joined = sql.SQL("WITH x AS (") + qx + sql.SQL("), y AS (") + qy + sql.SQL("), j AS (SELECT x.lei_code, x.nsa, x.v AS xv, y.v AS yv FROM x JOIN y USING (lei_code)) ")
    params = px + py
    st = _one(cur, joined + sql.SQL("""SELECT count(*), corr(xv, yv) FROM j"""), params)
    n_pairs, pearson = st
    spearman = None
    if n_pairs and n_pairs > 2:
        spearman = _one(cur, joined + sql.SQL(
            """, r AS (SELECT rank() OVER (ORDER BY xv) + (count(*) OVER (PARTITION BY xv) - 1) / 2.0 AS rx,
                              rank() OVER (ORDER BY yv) + (count(*) OVER (PARTITION BY yv) - 1) / 2.0 AS ry FROM j)
               SELECT corr(rx, ry) FROM r"""), params)[0]
    cur.execute(joined + sql.SQL("SELECT lei_code, nsa, xv, yv FROM j ORDER BY md5(lei_code) LIMIT %s"), params + [max_points])
    pts = [{"lei": r[0], "country": r[1], "x": r[2], "y": r[3]} for r in cur.fetchall()]
    clean = lambda v: None if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v
    return {"n_pairs": n_pairs, "points": pts, "sampled": n_pairs > len(pts), "stats": {"pearson": clean(pearson), "spearman": clean(spearman)}}


def item_label(cur, ds: Dataset, item: str) -> str | None:
    row = _one(cur, sql.SQL("SELECT max(label) FROM {} WHERE item = %s").format(ds.table), (item,))
    return row[0] if row else None
