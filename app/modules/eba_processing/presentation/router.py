"""HTTP methods of the processing module: look at the staged data (preview, profile, nulls, histogram, scatter) and validate it."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.api import problem_responses
from app.core.config import get_schema
from app.modules.eba_processing.application import analytics as analytics_uc
from app.modules.eba_processing.application import datasets as datasets_uc
from app.modules.eba_processing.application import validation as validation_uc
from app.modules.eba_processing.domain import (
    AGGREGATIONS, CLIPS, DEFAULT_BINS, DEFAULT_PAGE_SIZE, DEFAULT_SCATTER_POINTS, DEFAULT_TOP_VALUES, MAX_BINS, MAX_PAGE_SIZE, MAX_SCATTER_POINTS,
    MAX_TOP_VALUES, QUERY_TIMEOUT_SECONDS, RULES, SCALES, SEVERITIES, Filters, parse_dims,
)
from app.modules.eba_processing.presentation.schemas import (
    DatasetSummary, HistogramResponse, ItemPage, NullAnalysis, PreviewPage, ProcessingConfig, ProfileResponse, ScatterResponse, ValidationQueued, ValidationState,
)

TAG = "processing"
PERIOD = Query(default=None, pattern=r"^[0-9]{6}$", description="Period as in the file, YYYYMM", examples=["202006"])
DIM = Query(default=None, description="Dimension filter column:value, repeatable (e.g. perf_status:2)")


def build_router(schema: str | None = None) -> APIRouter:
    schema = schema or get_schema()
    router = APIRouter(prefix="/api", tags=[TAG])

    def filters(period=None, lei=None, item=None, dim=None, exclude_aggregate=False) -> Filters:
        return Filters(period=period, lei=lei, item=item, dims=parse_dims(dim), exclude_aggregate=exclude_aggregate)

    @router.get("/processing/config", response_model=ProcessingConfig, operation_id="get_processing_config", summary="Limits, enumerations and the validation rules")
    def config():
        """Everything the interface needs to build its controls without hard-coding: limits, allowed values and the rule catalogue."""
        return ProcessingConfig(
            default_page_size=DEFAULT_PAGE_SIZE, max_page_size=MAX_PAGE_SIZE, default_bins=DEFAULT_BINS, max_bins=MAX_BINS,
            default_scatter_points=DEFAULT_SCATTER_POINTS, max_scatter_points=MAX_SCATTER_POINTS, max_top_values=MAX_TOP_VALUES,
            query_timeout_seconds=QUERY_TIMEOUT_SECONDS, aggregations=list(AGGREGATIONS), scales=list(SCALES), clips=list(CLIPS), severities=list(SEVERITIES),
            column_roles=["key", "label", "measure", "annotation", "dimension"],
            validation_rules=[dict(id=r.id, title=r.title, severity=r.severity, description=r.description) for r in RULES],
        )

    @router.get("/imports/{import_id}/datasets", response_model=list[DatasetSummary], operation_id="list_datasets", summary="Staged data files of an import",
                responses=problem_responses(404))
    def list_datasets(import_id: int):
        """One entry per data file whose staging table still exists: columns with roles, rows and the periods found.
        Empty when the staging tables were dropped."""
        return datasets_uc.datasets_of_import(import_id, schema)

    @router.get("/datasets/{file_id}", response_model=DatasetSummary, operation_id="get_dataset", summary="One staged data file", responses=problem_responses(404))
    def get_dataset(file_id: int):
        return datasets_uc.dataset_info(file_id, schema)

    @router.get("/datasets/{file_id}/preview", response_model=PreviewPage, operation_id="preview_dataset", summary="A page of rows",
                responses=problem_responses(404, 422, 504))
    def preview(file_id: int, page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
                sort: str | None = Query(default=None, description="Column to sort by (amount sorts numerically)"), order: str = Query(default="asc", pattern="^(asc|desc)$"),
                period: str | None = PERIOD, lei: str | None = None, item: str | None = None, dim: list[str] | None = DIM, exclude_aggregate: bool = False):
        """Rows exactly as loaded (all text). Filters combine with AND; unknown columns are refused with the list of valid ones."""
        return datasets_uc.preview(file_id, schema, filters(period, lei, item, dim, exclude_aggregate), page, page_size, sort, order)

    @router.get("/datasets/{file_id}/items", response_model=ItemPage, operation_id="list_items", summary="Catalogue of items with null and label checks",
                responses=problem_responses(404, 422, 504))
    def list_items(file_id: int, q: str | None = Query(default=None, description="Search in item code and label"), page: Annotated[int, Query(ge=1)] = 1,
                   page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE, period: str | None = PERIOD, exclude_aggregate: bool = True):
        """The list the interface needs to fill the item selectors of the histogram and the scatter plot."""
        return datasets_uc.items(file_id, schema, filters(period=period, exclude_aggregate=exclude_aggregate), q, page, page_size)

    @router.get("/datasets/{file_id}/profile", response_model=ProfileResponse, operation_id="profile_dataset", summary="Per-column profile: nulls, distinct values, top values",
                responses=problem_responses(404, 422, 504))
    def profile(file_id: int, distinct: bool = True, top: Annotated[int, Query(ge=0, le=MAX_TOP_VALUES)] = DEFAULT_TOP_VALUES, period: str | None = PERIOD,
                exclude_aggregate: bool = False):
        return analytics_uc.profile(file_id, schema, filters(period=period, exclude_aggregate=exclude_aggregate), distinct, top)

    @router.get("/datasets/{file_id}/nulls", response_model=NullAnalysis, operation_id="nulls_dataset", summary="Null analysis by period or by item",
                responses=problem_responses(404, 422, 504))
    def nulls(file_id: int, by: str = Query(default="period", pattern="^(period|item)$", description="period: a matrix of nulls per column and period; item: the items with the most empty amounts"),
              columns: list[str] | None = Query(default=None, description="Columns to count (by=period); default all"), limit: Annotated[int, Query(ge=1, le=200)] = 20,
              exclude_aggregate: bool = False):
        return analytics_uc.nulls(file_id, schema, filters(exclude_aggregate=exclude_aggregate), by, columns, limit)

    @router.get("/datasets/{file_id}/histogram", response_model=HistogramResponse, operation_id="histogram_dataset", summary="Distribution of the amounts of one item",
                responses=problem_responses(404, 422, 504))
    def histogram(file_id: int, item: str = Query(description="Item code (see /items)"), period: str | None = PERIOD, bins: Annotated[int, Query(ge=1, le=MAX_BINS)] = DEFAULT_BINS,
                  scale: str = Query(default="linear", pattern="^(linear|log)$"), clip: str = Query(default="none", pattern="^(none|p01-p99|iqr)$"),
                  dim: list[str] | None = DIM, exclude_aggregate: bool = True):
        """Equal-width (or logarithmic) bins with summary statistics. `clip` hides the tails from the bins but still counts them in `outside`."""
        return analytics_uc.histogram(file_id, schema, filters(period, None, item, dim, exclude_aggregate), bins, scale, clip)

    @router.get("/datasets/{file_id}/scatter", response_model=ScatterResponse, operation_id="scatter_dataset", summary="One value per bank for two (item, period) choices",
                responses=problem_responses(404, 422, 504))
    def scatter(file_id: int, x_item: str, y_item: str, x_period: Annotated[str, Query(pattern=r"^[0-9]{6}$")], y_period: Annotated[str, Query(pattern=r"^[0-9]{6}$")],
                agg: str = Query(default="single", pattern="^(single|sum|mean|min|max)$", description="How to combine several rows of a bank (single refuses them)"),
                x_dim: list[str] | None = DIM, y_dim: list[str] | None = DIM, max_points: Annotated[int, Query(ge=10, le=MAX_SCATTER_POINTS)] = DEFAULT_SCATTER_POINTS,
                exclude_aggregate: bool = True):
        """Pairs the two values by bank (LEI). Use two items in one period to relate indicators, or one item in two periods to see change.
        `n_pairs` is always the full number; when it exceeds `max_points` a reproducible sample is returned and `sampled` is true."""
        return analytics_uc.scatter(file_id, schema, filters(x_period, None, x_item, x_dim, exclude_aggregate), filters(y_period, None, y_item, y_dim, exclude_aggregate), agg, max_points)

    @router.post("/imports/{import_id}/validation", status_code=202, response_model=ValidationQueued, operation_id="queue_validation", summary="Queue the validation of a staged import",
                 responses=problem_responses(404, 409))
    def queue_validation(import_id: int):
        """Runs the rule catalogue (see /api/processing/config) in the worker. Poll `GET` of the same path. Idempotent while a run is waiting or running."""
        return validation_uc.enqueue_validation(import_id, schema)

    @router.get("/imports/{import_id}/validation", response_model=ValidationState, operation_id="get_validation", summary="State and latest report of the validation",
                responses=problem_responses(404))
    def get_validation(import_id: int):
        """`job` is the latest validation job (null if never queued), `report` the latest finished report (null until one exists).
        A report without errors moves the import to `validated`."""
        return validation_uc.get_validation(import_id, schema)

    return router
