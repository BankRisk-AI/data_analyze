from __future__ import annotations

from psycopg2 import sql

from app.core.database import connect
from app.core.exceptions import InvalidParameter
from app.modules.eba_public_analysis.domain import DATASETS
from app.modules.eba_public_analysis.infrastructure.db import ensure_active, validate_page


def _view(dataset: str) -> str:
    key = dataset.removeprefix("tr_")
    try:
        return DATASETS[key]
    except KeyError as exc:
        raise InvalidParameter(f"unsupported public dataset '{dataset}'") from exc


def periods(schema: str) -> list[dict]:
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT version_id, year, quarter, period_end, import_id,
                                  (SELECT count(*) FROM fact_oth WHERE version_id=v.version_id),
                                  (SELECT count(*) FROM fact_cre WHERE version_id=v.version_id),
                                  (SELECT count(*) FROM fact_mrk WHERE version_id=v.version_id)
                                  ,(SELECT count(*) FROM fact_sov WHERE version_id=v.version_id)
                           FROM dataset_version v WHERE is_active
                           ORDER BY year, quarter, version_no""")
            return [{"version_id": r[0], "year": r[1], "quarter": r[2], "period_end": r[3].isoformat(),
                     "import_id": r[4], "rows_oth": r[5], "rows_cre": r[6], "rows_mrk": r[7], "rows_sov": r[8]} for r in cur.fetchall()]
    finally:
        conn.close()


def preview(version_id: int, dataset: str, schema: str, page: int, page_size: int) -> dict:
    validate_page(page, page_size)
    view = _view(dataset)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            ensure_active(cur, version_id)
            cur.execute(f"SELECT count(*) FROM {view} WHERE version_id=%s", (version_id,))
            total = cur.fetchone()[0]
            cur.execute(f"SELECT * FROM {view} WHERE version_id=%s ORDER BY lei_code, item LIMIT %s OFFSET %s",
                        (version_id, page_size, (page - 1) * page_size))
            names = [d[0] for d in cur.description]
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "columns": names,
                    "rows": [dict(zip(names, row)) for row in cur.fetchall()], "total": total,
                    "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}
    finally:
        conn.close()


def profile(version_id: int, dataset: str, schema: str) -> dict:
    view = _view(dataset)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            ensure_active(cur, version_id)
            cur.execute(f"SELECT count(*), min(amount), max(amount), avg(amount) FROM {view} WHERE version_id=%s", (version_id,))
            rows, minimum, maximum, mean = cur.fetchone()
            cur.execute(f"""SELECT column_name FROM information_schema.columns
                            WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position""",
                        (view,))
            columns = []
            for (name,) in cur.fetchall():
                cur.execute(
                    sql.SQL("SELECT count(*)-count({}), count(DISTINCT {}) FROM {} WHERE version_id=%s")
                    .format(sql.Identifier(name), sql.Identifier(name), sql.Identifier(view)),
                    (version_id,),
                )
                nulls, distinct = cur.fetchone()
                columns.append({"name": name, "nulls": nulls, "distinct": distinct})
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "rows": rows,
                    "columns": columns, "amount": {"min": minimum, "max": maximum, "mean": mean}}
    finally:
        conn.close()


def histogram(version_id: int, dataset: str, item: str, period: str, schema: str, bins: int = 20) -> dict:
    if bins < 1 or bins > 200:
        raise InvalidParameter("bins must be between 1 and 200")
    view = _view(dataset)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            ensure_active(cur, version_id)
            cur.execute(f"""SELECT count(*), min(amount), max(amount), avg(amount)
                            FROM {view} WHERE version_id=%s AND item=%s AND period=%s""",
                        (version_id, item, period))
            count, minimum, maximum, mean = cur.fetchone()
            if not count or minimum is None or minimum == maximum:
                return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "item": item,
                        "period": period, "rows": count, "bins": [], "stats": {"min": minimum, "max": maximum, "mean": mean}}
            width = (maximum - minimum) / bins
            cur.execute(f"""SELECT least(floor((amount-%s)/%s)::int+1,%s), count(*)
                            FROM {view} WHERE version_id=%s AND item=%s AND period=%s
                            GROUP BY 1 ORDER BY 1""", (minimum, width, bins, version_id, item, period))
            counts = dict(cur.fetchall())
            edges = [{"x0": minimum + i * width, "x1": minimum + (i + 1) * width, "count": counts.get(i + 1, 0)}
                     for i in range(bins)]
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "item": item,
                    "period": period, "rows": count, "bins": edges,
                    "stats": {"min": minimum, "max": maximum, "mean": mean}}
    finally:
        conn.close()


def aggregate(version_id: int, dataset: str, item: str, period: str, function: str, schema: str) -> dict:
    if function not in {"sum", "avg", "min", "max", "count"}:
        raise InvalidParameter("function must be sum, avg, min, max or count")
    view = _view(dataset)
    expression = "count(*)" if function == "count" else f"{function}(amount)"
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            ensure_active(cur, version_id)
            cur.execute(f"SELECT {expression} FROM {view} WHERE version_id=%s AND item=%s AND period=%s",
                        (version_id, item, period))
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "item": item,
                    "period": period, "function": function, "value": cur.fetchone()[0]}
    finally:
        conn.close()


def scatter(version_id: int, dataset: str, item_x: str, item_y: str, period: str, schema: str) -> dict:
    view = _view(dataset)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            ensure_active(cur, version_id)
            cur.execute(
                f"""SELECT x.lei_code, x.amount, y.amount
                    FROM {view} x JOIN {view} y
                      ON y.version_id=x.version_id AND y.lei_code=x.lei_code AND y.period=x.period
                    WHERE x.version_id=%s AND x.period=%s AND x.item=%s AND y.item=%s
                    ORDER BY x.lei_code""",
                (version_id, period, item_x, item_y),
            )
            points = [{"lei_code": r[0], "x": r[1], "y": r[2]} for r in cur.fetchall()]
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"),
                    "item_x": item_x, "item_y": item_y, "period": period, "points": points}
    finally:
        conn.close()
