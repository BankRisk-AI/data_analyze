"""Request and response models of the processing API (they define the OpenAPI schemas)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ColumnInfo(BaseModel):
    name: str = Field(examples=["perf_status"])
    role: str = Field(description="key, label, measure, annotation or dimension", examples=["dimension"])
    position: int | None = Field(default=None, description="1-based position in the file")


class PeriodInfo(BaseModel):
    period: str = Field(description="As in the file (YYYYMM)", examples=["202006"])
    year: int
    quarter: int = Field(description="0 when the month is invalid")
    banks: int = Field(description="Distinct banks, aggregate bucket excluded")
    rows: int = Field(description="Rows, aggregate bucket excluded")


class DatasetSummary(BaseModel):
    file_id: int
    import_id: int
    file_name: str
    file_type: str = Field(examples=["tr_cre"])
    rows: int = Field(description="Rows in the staging table (aggregate bucket included)")
    columns: list[ColumnInfo]
    periods: list[PeriodInfo]


class PreviewPage(BaseModel):
    file_id: int
    columns: list[ColumnInfo]
    rows: list[dict[str, Any]] = Field(description="One object per row; empty cells are null")
    total: int = Field(description="Rows matching the filters")
    page: int
    page_size: int
    pages: int
    sort: str | None = None
    order: str = "asc"
    elapsed_ms: float


class ItemRow(BaseModel):
    item: str = Field(examples=["2020140"])
    label: str | None = None
    rows: int
    banks: int
    null_amount: int = Field(description="Rows with an empty amount")
    non_numeric_amount: int = Field(description="Rows whose amount is not a number")
    labels: int = Field(description="Distinct labels of the item (more than 1 is suspicious)")


class ItemPage(BaseModel):
    file_id: int
    items: list[ItemRow]
    total: int
    page: int
    page_size: int
    pages: int
    elapsed_ms: float


class TopValue(BaseModel):
    value: str | None
    count: int


class ColumnProfile(BaseModel):
    name: str
    role: str
    non_null: int
    nulls: int = Field(description="Empty or blank cells")
    null_pct: float
    distinct: int | None = Field(default=None, description="null when distinct=false was requested")
    min_length: int | None = None
    max_length: int | None = None
    top_values: list[TopValue] = Field(default_factory=list, description="Most frequent values, only for columns with few distinct values")


class AmountSummary(BaseModel):
    numeric: int
    non_numeric: int
    min: float | None = None
    max: float | None = None
    mean: float | None = None


class ProfileResponse(BaseModel):
    file_id: int
    rows: int
    columns: list[ColumnProfile]
    amount: AmountSummary
    elapsed_ms: float


class NullGroup(BaseModel):
    group: str = Field(description="The period or the item")
    label: str | None = Field(default=None, description="Item label (by=item)")
    rows: int
    nulls: dict[str, int]
    null_pct: dict[str, float]


class NullAnalysis(BaseModel):
    file_id: int
    by: str = Field(examples=["period"])
    columns: list[str]
    groups: list[NullGroup]
    elapsed_ms: float


class HistogramBin(BaseModel):
    x0: float
    x1: float
    count: int


class HistogramStats(BaseModel):
    min: float
    p01: float
    p25: float
    median: float
    p75: float
    p99: float
    max: float
    mean: float
    std: float | None = None


class ValueRange(BaseModel):
    lo: float
    hi: float


class HistogramResponse(BaseModel):
    file_id: int
    item: str
    label: str | None = None
    period: str | None = None
    rows: int = Field(description="Rows of the selection")
    n: int = Field(description="Numeric amounts")
    nulls: int
    non_numeric: int
    non_positive: int = Field(description="Values <= 0 left out of a logarithmic histogram")
    scale: str
    clip: str
    bins: list[HistogramBin]
    stats: HistogramStats | None = None
    range: ValueRange | None = None
    outside: int = Field(description="Numeric values counted but not drawn (clipped or off-scale)")
    note: str | None = None
    elapsed_ms: float


class ScatterPoint(BaseModel):
    lei: str
    country: str | None = None
    x: float
    y: float


class ScatterAxis(BaseModel):
    item: str
    period: str
    label: str | None = None


class ScatterStats(BaseModel):
    pearson: float | None = None
    spearman: float | None = None


class ScatterResponse(BaseModel):
    file_id: int
    agg: str
    x: ScatterAxis
    y: ScatterAxis
    n_pairs: int = Field(description="Banks that have both values")
    points: list[ScatterPoint]
    sampled: bool = Field(description="True when n_pairs is larger than the points returned (a reproducible sample by hashed LEI)")
    max_points: int
    stats: ScatterStats
    elapsed_ms: float


class ValidationQueued(BaseModel):
    job_id: int
    status: str = Field(examples=["pending"])
    created: bool = Field(description="False when a validation was already waiting or running and that job is returned")


class ValidationJob(BaseModel):
    job_id: int
    status: str = Field(description="pending, processing, completed or failed")
    progress: int
    message: str | None = None
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class IssueModel(BaseModel):
    rule: str = Field(examples=["V02"])
    title: str
    severity: str = Field(description="error, warning or info")
    status: str = Field(description="passed or failed")
    affected_rows: int
    detail: str
    examples: list[dict[str, Any]]
    seconds: float = 0.0


class FileValidationModel(BaseModel):
    file_id: int
    file_name: str
    file_type: str
    rows: int
    errors: int
    warnings: int
    infos: int
    issues: list[IssueModel]


class ValidationSummary(BaseModel):
    errors: int
    warnings: int
    infos: int
    can_proceed: bool = Field(description="True when no rule of severity error failed")


class ValidationReportModel(BaseModel):
    import_id: int
    generated_at: str
    seconds: float
    summary: ValidationSummary
    files: list[FileValidationModel]


class ValidationState(BaseModel):
    import_id: int
    import_status: str | None = None
    job: ValidationJob | None = None
    report: ValidationReportModel | None = None


class RuleInfo(BaseModel):
    id: str
    title: str
    severity: str
    description: str


class ProcessingConfig(BaseModel):
    default_page_size: int
    max_page_size: int
    default_bins: int
    max_bins: int
    default_scatter_points: int
    max_scatter_points: int
    max_top_values: int
    query_timeout_seconds: int
    aggregations: list[str]
    scales: list[str]
    clips: list[str]
    severities: list[str]
    column_roles: list[str]
    validation_rules: list[RuleInfo]
