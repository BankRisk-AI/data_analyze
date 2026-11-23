from __future__ import annotations

from typing import Annotated, Literal
from fastapi import APIRouter, Path, Query

from app.core.api import problem_responses
from app.core.config import get_schema
from app.modules.eba_public_analysis.application import alerts as alert_svc
from app.modules.eba_public_analysis.application import datasets as dataset_svc
from app.modules.eba_public_analysis.application import panel as panel_svc
from app.modules.eba_public_analysis.domain import MAX_PAGE_SIZE
from app.modules.eba_public_analysis.presentation.schemas import (
    Aggregate, BankList, CrossSection, Histogram, IndicatorSeries, PanelFeatures,
    PanelSeries, Preview, Profile, PublicPeriod, ReportQuarter, ReportType,
    ReportYear, Scatter, AlertProfile, AlertSummaryResponse, AlertListResponse,
    BankAlerts, AlertDetail,
)

TAG = "public-analysis"
Dataset = Literal["oth", "cre", "mrk", "sov", "tr_oth", "tr_cre", "tr_mrk", "tr_sov"]
AggregateFunction = Literal["sum", "avg", "min", "max", "count"]


def build_router(schema: str | None = None) -> APIRouter:
    schema = schema or get_schema()
    router = APIRouter(prefix="/api/public", tags=[TAG])

    @router.get("/periods", response_model=list[PublicPeriod], operation_id="list_public_analysis_periods",
                summary="List active public periods")
    def list_periods():
        return dataset_svc.periods(schema)

    @router.get("/versions/{version_id}/datasets/{dataset}/preview", response_model=Preview,
                operation_id="preview_public_analysis", summary="Preview promoted public data",
                responses=problem_responses(404, 422))
    def preview(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")],
                page: Annotated[int, Query(ge=1)] = 1,
                page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50):
        return dataset_svc.preview(version_id, dataset, schema, page, page_size)

    @router.get("/versions/{version_id}/datasets/{dataset}/profile", response_model=Profile,
                operation_id="profile_public_analysis", summary="Profile promoted public data",
                responses=problem_responses(404, 422))
    def public_profile(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")]):
        return dataset_svc.profile(version_id, dataset, schema)

    @router.get("/versions/{version_id}/datasets/{dataset}/histogram", response_model=Histogram,
                operation_id="histogram_public_analysis", summary="Histogram data for a public item",
                responses=problem_responses(404, 422))
    def public_histogram(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")],
                         item: Annotated[str, Query(description="Indicator code")],
                         period: Annotated[str, Query(description="YYYYMM period")],
                         bins: Annotated[int, Query(ge=1, le=200, description="Number of histogram bins")] = 20):
        return dataset_svc.histogram(version_id, dataset, item, period, schema, bins)

    @router.get("/versions/{version_id}/datasets/{dataset}/aggregate", response_model=Aggregate,
                operation_id="aggregate_public_analysis", summary="Calculate a backend public aggregation",
                responses=problem_responses(404, 422))
    def public_aggregate(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")],
                         item: Annotated[str, Query(description="Indicator code")],
                         period: Annotated[str, Query(description="YYYYMM period")],
                         function: Annotated[AggregateFunction, Query(description="Aggregation function")] = "sum"):
        return dataset_svc.aggregate(version_id, dataset, item, period, function, schema)

    @router.get("/versions/{version_id}/datasets/{dataset}/scatter", response_model=Scatter,
                operation_id="scatter_public_analysis", summary="Scatter plot points for two public items",
                responses=problem_responses(404, 422))
    def public_scatter(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")],
                       item_x: Annotated[str, Query(description="Indicator code for the x axis")],
                       item_y: Annotated[str, Query(description="Indicator code for the y axis")],
                       period: Annotated[str, Query(description="YYYYMM period")]):
        return dataset_svc.scatter(version_id, dataset, item_x, item_y, period, schema)

    @router.get("/report-types", response_model=list[ReportType], operation_id="list_report_types",
                summary="List report types and datasets", responses=problem_responses(422))
    def list_report_types():
        return panel_svc.report_types(schema)

    @router.get("/report-types/{report_type}/years", response_model=list[ReportYear],
                operation_id="list_report_type_years", summary="List years for a report type",
                responses=problem_responses(422))
    def list_report_type_years(report_type: str):
        return panel_svc.report_years(report_type, schema)

    @router.get("/report-types/{report_type}/years/{year}/quarters", response_model=list[ReportQuarter],
                operation_id="list_report_type_quarters", summary="List quarters for a report type",
                responses=problem_responses(422))
    def list_report_type_quarters(report_type: str, year: Annotated[int, Path(ge=2000, le=2100)]):
        return panel_svc.report_quarters(report_type, year, schema)

    @router.get("/banks", response_model=BankList, operation_id="list_banks",
                summary="List banks and panel coverage", responses=problem_responses(422))
    def list_banks(page: Annotated[int, Query(ge=1)] = 1,
                   page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
                   country: str | None = None, search: str | None = None):
        return panel_svc.banks(schema, page, page_size, country, search)

    @router.get("/banks/{bank_id}/panel", response_model=PanelSeries,
                operation_id="get_bank_panel", summary="Get all panel periods for a bank",
                responses=problem_responses(404, 422))
    def get_bank_panel(bank_id: int):
        return panel_svc.bank_panel(bank_id, schema)

    @router.get("/panel/cross-section", response_model=CrossSection,
                operation_id="get_panel_cross_section", summary="Get a panel feature cross-section",
                responses=problem_responses(404, 422))
    def get_panel_cross_section(period: Annotated[str, Query(min_length=6, max_length=6)],
                                feature: str, exclude_specialist: bool = False):
        return panel_svc.cross_section(period, feature, schema, exclude_specialist)

    @router.get("/panel/features", response_model=PanelFeatures,
                operation_id="list_panel_features", summary="Describe panel features and flags")
    def list_panel_features():
        return panel_svc.feature_definitions()

    @router.get("/indicators/{indicator_id}/series", response_model=IndicatorSeries,
                operation_id="get_indicator_series", summary="Get a bank indicator series",
                responses=problem_responses(404, 422))
    def get_indicator_series(indicator_id: int, bank_id: Annotated[int, Query(ge=1)]):
        return panel_svc.indicator_series(indicator_id, bank_id, schema)

    @router.get("/alerts/profiles", response_model=list[AlertProfile],
                operation_id="list_alert_profiles", summary="List evaluated alert profiles")
    def list_alert_profiles():
        return alert_svc.alert_profiles(schema)

    @router.get("/alerts/summary", response_model=AlertSummaryResponse,
                operation_id="summarize_alerts", summary="Summarize alerts by period",
                responses=problem_responses(404, 422))
    def summarize_alerts(profile: Annotated[str | None, Query(description="Profile name, full SHA, or unique SHA prefix (8+ characters)")] = None):
        return alert_svc.alert_summary(profile, schema)

    @router.get("/alerts", response_model=AlertListResponse,
                operation_id="list_alerts", summary="List alerts for a period",
                responses=problem_responses(404, 422))
    def list_alerts(period: Annotated[str, Query(min_length=6, max_length=6)],
                    profile: Annotated[str | None, Query(description="Profile name, full SHA, or unique SHA prefix (8+ characters)")] = None,
                    level: str | None = None,
                    exclude_specialist: bool = True,
                    page: Annotated[int, Query(ge=1)] = 1,
                    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50):
        return alert_svc.alerts(period, profile, level, exclude_specialist, page, page_size, schema)

    @router.get("/banks/{bank_id}/alerts", response_model=BankAlerts,
                operation_id="get_bank_alerts", summary="Get a bank alert timeline",
                responses=problem_responses(404, 422))
    def get_bank_alerts(bank_id: Annotated[int, Path(ge=1)],
                        profile: Annotated[str | None, Query(description="Profile name, full SHA, or unique SHA prefix (8+ characters)")] = None):
        return alert_svc.bank_alerts(bank_id, profile, schema)

    @router.get("/alerts/{alert_id}", response_model=AlertDetail,
                operation_id="get_alert", summary="Get alert details",
                responses=problem_responses(404, 422))
    def get_alert(alert_id: Annotated[int, Path(ge=1)],
                  profile: Annotated[str | None, Query(description="Profile name, full SHA, or unique SHA prefix (8+ characters)")] = None):
        return alert_svc.alert_detail(alert_id, profile, schema)

    return router
