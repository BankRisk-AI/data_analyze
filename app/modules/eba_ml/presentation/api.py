from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, ConfigDict, Field

from app.core.api import problem_responses
from app.modules.eba_ml.application import service

TAG = "ml"
PageParam = Annotated[int, Query(ge=1)]
SizeParam = Annotated[int, Query(ge=1, le=200)]


class DatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    grid: str
    feature_set: str = "robustness_v1"
    content_hash: str = "0" * 64


class ExperimentRequest(DatasetRequest):
    algorithms: list[str] = Field(default_factory=lambda: ["XGB"])
    seed: int = 20261121
    folds: list[int] = Field(default_factory=lambda: [2017, 2018, 2019, 2020, 2021])
    budget: int = Field(default=60, ge=1, le=60)
    thresholds: list[str] = Field(default_factory=lambda: ["matched_far", "max_ur_0_9"])


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_name: str


def build_router(schema: str | None = None):
    router = APIRouter(prefix="/api/ml", tags=[TAG])

    @router.get("/options", operation_id="get_ml_options", summary="ML options")
    def options(): return service.options()

    @router.get("/datasets", operation_id="list_ml_datasets", summary="List ML datasets")
    def datasets(page: PageParam = 1, page_size: SizeParam = 50):
        return service.list_rows("ml_dataset", page, page_size)

    @router.post("/datasets", operation_id="create_ml_dataset", summary="Create ML dataset",
                 responses=problem_responses(422))
    def create_dataset(payload: DatasetRequest): return service.create_dataset(payload.model_dump())

    @router.get("/datasets/{dataset_id}", operation_id="get_ml_dataset", summary="Get ML dataset",
                 responses=problem_responses(404))
    def dataset(dataset_id: int): return service.get_row("ml_dataset", "dataset_id", dataset_id)

    @router.get("/experiments", operation_id="list_ml_experiments", summary="List ML experiments")
    def experiments(page: PageParam = 1, page_size: SizeParam = 50):
        return service.list_rows("ml_experiment", page, page_size)

    @router.post("/experiments", operation_id="create_ml_experiment", summary="Create ML experiment",
                 responses=problem_responses(422))
    def create_experiment(payload: ExperimentRequest): return service.create_experiment(payload.model_dump())

    @router.get("/experiments/{experiment_id}", operation_id="get_ml_experiment", summary="Get ML experiment",
                 responses=problem_responses(404))
    def experiment(experiment_id: int): return service.get_row("ml_experiment", "experiment_id", experiment_id)

    @router.post("/experiments/{experiment_id}/cancel", operation_id="cancel_ml_experiment", summary="Cancel ML experiment",
                 responses=problem_responses(404, 400))
    def cancel(experiment_id: int): return service.cancel_experiment(experiment_id)

    @router.get("/models", operation_id="list_ml_models", summary="List ML models")
    def models(page: PageParam = 1, page_size: SizeParam = 50, status: str | None = None):
        where = "WHERE status=%s" if status else ""
        return service.list_rows("ml_model", page, page_size, where, (status,) if status else ())

    @router.post("/models/compare", operation_id="compare_ml_models", summary="Compare ML models")
    def compare(model_ids: list[int] = Body(..., embed=True)):
        if not 2 <= len(model_ids) <= 4: from app.core.exceptions import InvalidParameter; raise InvalidParameter("compare requires 2 to 4 models")
        return {"models": [service.get_row("ml_model", "model_id", value) for value in model_ids]}

    @router.get("/models/{model_id}", operation_id="get_ml_model", summary="Get ML model",
                 responses=problem_responses(404))
    def model(model_id: int): return service.get_row("ml_model", "model_id", model_id)

    @router.post("/models/{model_id}/champion", operation_id="promote_ml_model", summary="Promote ML champion",
                 responses=problem_responses(404, 400))
    def champion(model_id: int): return service.promote_model(model_id)

    @router.post("/models/{model_id}/archive", operation_id="archive_ml_model", summary="Archive ML model",
                 responses=problem_responses(404, 409))
    def archive(model_id: int): return service.archive_model(model_id)

    @router.delete("/models/{model_id}", operation_id="delete_ml_model", summary="Delete ML model",
                   responses=problem_responses(404, 409, 422))
    def delete(model_id: int, payload: DeleteRequest):
        service.hard_delete_model(model_id, payload.model_name)
        return {"model_id": model_id, "status": "deleted"}

    @router.get("/predictions", operation_id="list_ml_predictions", summary="List ML predictions")
    def predictions(page: PageParam = 1, page_size: SizeParam = 50, champion_only: bool = True):
        return service.list_predictions(page, page_size, champion_only)

    return router
