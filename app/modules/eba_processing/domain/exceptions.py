"""Domain-level exceptions for eba_processing."""
from app.core.exceptions import AppError, NotFoundError


class NothingToValidate(AppError):
    kind = "no-staging"
    status = 409
    title = "Nothing to validate"


class DatasetNotFound(NotFoundError):
    kind = "dataset-not-found"
    title = "Dataset not found"


class ImportNotFound(NotFoundError):
    kind = "not-found"
    title = "Import not found"
