"""SQL helpers for translating Filters into safe WHERE clauses. Identifiers are checked against the table's
real columns and values are always bound parameters: nothing the client sends is ever concatenated into SQL."""
from __future__ import annotations

from psycopg2 import sql

from app.modules.eba_processing.domain import Filters
from app.shared.sql.predicates import aggregate_rows_predicate


def conditions(ds, f: Filters) -> tuple[list[sql.Composable], list]:
    """The filters as SQL conditions (identifiers checked against the table) and their bound parameters."""
    conds: list[sql.Composable] = []
    params: list = []
    for name, value in (("period", f.period), ("lei_code", f.lei), ("item", f.item)):
        if value is not None:
            conds.append(sql.SQL("{} = %s").format(ds.col(name)))
            params.append(value)
    for name, value in f.dims.items():
        conds.append(sql.SQL("{} = %s").format(ds.col(name)))
        params.append(value)
    if f.exclude_aggregate:
        conds.append(sql.SQL("NOT " + aggregate_rows_predicate()))
    return conds, params


def clause(conds: list[sql.Composable], *extra: str) -> sql.Composable:
    """` WHERE a AND b ...`; `extra` are fragments written by us (never by the client), appended with AND. Empty when there is nothing."""
    parts = list(conds) + [sql.SQL(e) for e in extra]
    if not parts:
        return sql.SQL("")
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(parts)


def where(ds, f: Filters) -> tuple[sql.Composable, list]:
    conds, params = conditions(ds, f)
    return clause(conds), params
