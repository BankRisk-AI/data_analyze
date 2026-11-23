"""Refusals raised by the ingest module. They carry their HTTP status and title; the core renders them as problem+json."""
from app.core.exceptions import AppError


class IngestError(AppError):
    """Base exception for EBA ingestion errors."""

    kind = "ingest-error"
    status = 422
    title = "Import refused"


class DuplicateFile(IngestError):
    """Raised when a file has already been imported."""

    kind = "duplicate-file"
    status = 409
    title = "File already loaded"


class FileTooLarge(IngestError):
    """Raised when a file exceeds the configured size limit."""

    kind = "file-too-large"
    status = 413
    title = "File too large"


class UnreadableFile(IngestError):
    """Raised when a file cannot be read or parsed."""

    kind = "unreadable-file"
    status = 422
    title = "File cannot be read"


class StagingInUse(AppError):
    """Raised when staging tables cannot be dropped because a job is active."""

    kind = "staging-in-use"
    status = 409
    title = "Staging is in use"


class LoadError(AppError):
    """Raised when an import cannot be loaded into the fact tables."""

    kind = "load-error"
    status = 409
    title = "Import could not be loaded"
