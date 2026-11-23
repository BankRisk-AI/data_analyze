from typing import Any
from pydantic import BaseModel


class PublicPeriod(BaseModel):
    version_id: int
    year: int
    quarter: int
    period_end: str
    import_id: int
    rows_oth: int
    rows_cre: int
    rows_mrk: int
    rows_sov: int


class Preview(BaseModel):
    version_id: int
    dataset: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    pages: int


class Profile(BaseModel):
    version_id: int
    dataset: str
    rows: int
    columns: list[dict[str, Any]]
    amount: dict[str, Any]


class Histogram(BaseModel):
    version_id: int
    dataset: str
    item: str
    period: str
    rows: int
    bins: list[dict[str, Any]]
    stats: dict[str, Any]


class Aggregate(BaseModel):
    version_id: int
    dataset: str
    item: str
    period: str
    function: str
    value: float | int | None


class Scatter(BaseModel):
    version_id: int
    dataset: str
    item_x: str
    item_y: str
    period: str
    points: list[dict[str, Any]]


class ReportType(BaseModel):
    name: str
    label: str
    datasets: list[str]


class ReportYear(BaseModel):
    year: int


class ReportQuarter(BaseModel):
    period: str
    quarter: str
    reporting_date: str


class BankSummary(BaseModel):
    bank_id: int
    lei: str
    name: str | None
    country: str | None
    first_period: str | None
    last_period: str | None
    periods: int
    specialist_institution: bool


class BankList(BaseModel):
    rows: list[BankSummary]
    total: int
    page: int
    page_size: int


class PanelSeries(BaseModel):
    bank_id: int
    periods: list[dict[str, Any]]


class CrossSection(BaseModel):
    period: str
    feature: str
    values: list[dict[str, Any]]


class FeatureDefinition(BaseModel):
    name: str
    label: str
    formula: str
    unit: str
    first_period: str
    risk_direction: str


class PanelFeatures(BaseModel):
    features: list[FeatureDefinition]
    flags: dict[str, str]


class IndicatorSeries(BaseModel):
    indicator_id: int
    bank_id: int
    rows: list[dict[str, Any]]


class AlertProfile(BaseModel):
    profile_name: str
    version: str | None
    sha: str
    frozen: bool | None
    created_at: str
    rule_count: int
    families: list[str]


class AlertSummary(BaseModel):
    period: str
    counts: dict[str, int]
    shares: dict[str, float]


class AlertSummaryResponse(BaseModel):
    profile_name: str
    profile_sha256: str
    periods: list[AlertSummary]


class AlertListItem(BaseModel):
    alert_id: int
    bank_id: int
    lei: str
    bank_name: str | None
    period: str
    level: str
    reason: str | None
    family_scores: dict[str, Any] | None


class AlertListResponse(BaseModel):
    rows: list[AlertListItem]
    total: int
    page: int
    page_size: int


class BankAlerts(BaseModel):
    bank_id: int
    rows: list[dict[str, Any]]


class AlertDetail(BaseModel):
    alert_id: int
    bank_id: int
    version_id: int
    period: str
    level: str
    score: float | None
    reason: str | None
    family_scores: dict[str, Any] | None
    rules: list[dict[str, Any]]
    profile_name: str
    profile_version: str | None
    profile_sha256: str
