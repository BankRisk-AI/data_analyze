"""Use cases: column profile, null analysis, histogram and scatter."""
from __future__ import annotations

from app.core.exceptions import InvalidParameter
from app.modules.eba_processing.application.session import read_session
from app.modules.eba_processing.domain import (
    AGGREGATIONS, CLIPS, DEFAULT_BINS, DEFAULT_SCATTER_POINTS, DEFAULT_TOP_VALUES, MAX_BINS, MAX_SCATTER_POINTS, MAX_TOP_VALUES, SCALES, Filters,
)
from app.modules.eba_processing.infrastructure import sql_analytics as analytics
from app.modules.eba_processing.infrastructure.datasets import get_dataset


def profile(file_id: int, schema: str, filters: Filters, distinct: bool = True, top: int = DEFAULT_TOP_VALUES) -> dict:
    if not 0 <= top <= MAX_TOP_VALUES:
        raise InvalidParameter(f"top must be between 0 and {MAX_TOP_VALUES}")
    with read_session(schema) as (cur, ms):
        ds = get_dataset(cur, file_id)
        return {"file_id": file_id, **analytics.profile(cur, ds, filters, distinct, top), "elapsed_ms": ms()}


def nulls(file_id: int, schema: str, filters: Filters, by: str = "period", columns: list[str] | None = None, limit: int = 20) -> dict:
    if by not in ("period", "item"):
        raise InvalidParameter("by must be 'period' or 'item'")
    if not 1 <= limit <= 200:
        raise InvalidParameter("limit must be between 1 and 200")
    with read_session(schema) as (cur, ms):
        ds = get_dataset(cur, file_id)
        data = analytics.nulls_by_period(cur, ds, filters, columns or []) if by == "period" else analytics.nulls_by_item(cur, ds, filters, limit)
        return {"file_id": file_id, **data, "elapsed_ms": ms()}


def histogram(file_id: int, schema: str, filters: Filters, bins: int = DEFAULT_BINS, scale: str = "linear", clip: str = "none") -> dict:
    if filters.item is None:
        raise InvalidParameter("item is required: a distribution only makes sense for one item")
    if not 1 <= bins <= MAX_BINS:
        raise InvalidParameter(f"bins must be between 1 and {MAX_BINS}")
    if scale not in SCALES:
        raise InvalidParameter(f"scale must be one of {', '.join(SCALES)}")
    if clip not in CLIPS:
        raise InvalidParameter(f"clip must be one of {', '.join(CLIPS)}")
    with read_session(schema) as (cur, ms):
        ds = get_dataset(cur, file_id)
        data = analytics.histogram(cur, ds, filters, bins, scale, clip)
        return {"file_id": file_id, "item": filters.item, "label": analytics.item_label(cur, ds, filters.item), "period": filters.period, **data, "elapsed_ms": ms()}


def scatter(file_id: int, schema: str, x: Filters, y: Filters, agg: str = "single", max_points: int = DEFAULT_SCATTER_POINTS) -> dict:
    if agg not in AGGREGATIONS:
        raise InvalidParameter(f"agg must be one of {', '.join(AGGREGATIONS)}")
    if not 10 <= max_points <= MAX_SCATTER_POINTS:
        raise InvalidParameter(f"max_points must be between 10 and {MAX_SCATTER_POINTS}")
    with read_session(schema) as (cur, ms):
        ds = get_dataset(cur, file_id)
        data = analytics.scatter(cur, ds, x, y, agg, max_points)
        axes = {k: {"item": f.item, "period": f.period, "label": analytics.item_label(cur, ds, f.item)} for k, f in (("x", x), ("y", y))}
        return {"file_id": file_id, "agg": agg, **axes, **data, "max_points": max_points, "elapsed_ms": ms()}
