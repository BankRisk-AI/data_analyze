"""Use cases: which datasets an import has, their columns and periods, a page of rows, the item catalogue."""
from __future__ import annotations

from app.core.exceptions import InvalidParameter
from app.modules.eba_processing.application.session import read_session
from app.modules.eba_processing.domain import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SORT_ORDERS, Filters, column_role
from app.modules.eba_processing.infrastructure import sql_analytics as analytics
from app.modules.eba_processing.infrastructure.datasets import Dataset, get_dataset, list_datasets


def _check_page(page: int, page_size: int) -> None:
    if page < 1:
        raise InvalidParameter("page starts at 1")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise InvalidParameter(f"page_size must be between 1 and {MAX_PAGE_SIZE}")


def describe(cur, ds: Dataset) -> dict:
    total, periods = analytics.periods(cur, ds)
    return {
        "file_id": ds.file_id, "import_id": ds.import_id, "file_name": ds.file_name, "file_type": ds.file_type, "rows": total,
        "columns": [{"name": c, "role": column_role(c), "position": i + 1} for i, c in enumerate(ds.columns)],
        "periods": periods,
    }


def datasets_of_import(import_id: int, schema: str) -> list[dict]:
    with read_session(schema) as (cur, _):
        return [describe(cur, ds) for ds in list_datasets(cur, import_id)]


def dataset_info(file_id: int, schema: str) -> dict:
    with read_session(schema) as (cur, _):
        return describe(cur, get_dataset(cur, file_id))


def preview(file_id: int, schema: str, filters: Filters, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE, sort: str | None = None, order: str = "asc") -> dict:
    _check_page(page, page_size)
    if order not in SORT_ORDERS:
        raise InvalidParameter(f"order must be one of {', '.join(SORT_ORDERS)}")
    with read_session(schema) as (cur, ms):
        ds = get_dataset(cur, file_id)
        if sort is not None:
            ds.col(sort)                                   # unknown column -> 422 with the list of columns
        data = analytics.preview(cur, ds, filters, page, page_size, sort, order)
        pages = max(1, -(-data["total"] // page_size))
        return {"file_id": file_id, "columns": [{"name": c, "role": column_role(c)} for c in ds.columns], "rows": data["rows"], "total": data["total"],
                "page": page, "page_size": page_size, "pages": pages, "sort": sort, "order": order, "elapsed_ms": ms()}


def items(file_id: int, schema: str, filters: Filters, q: str | None = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    _check_page(page, page_size)
    with read_session(schema) as (cur, ms):
        ds = get_dataset(cur, file_id)
        data = analytics.items(cur, ds, filters, q, page, page_size)
        return {"file_id": file_id, **data, "page": page, "page_size": page_size, "pages": max(1, -(-data["total"] // page_size)), "elapsed_ms": ms()}
