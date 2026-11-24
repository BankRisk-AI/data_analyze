from app.core.database import init_database
from app.modules.eba_ingest.application.queries import drop_staging, get_import, list_imports, show
from app.modules.eba_ingest.application.staging_service import ingest, process_import
from app.modules.eba_ingest.application.upload_service import DEFAULT_MAX_BYTES, enqueue_import


def init_db(schema: str = "public") -> None:
    init_database(schema)


__all__ = [
    "DEFAULT_MAX_BYTES",
    "ingest", "init_db",
    "drop_staging",
    "show",
    "list_imports",
    "get_import",
    "enqueue_import",
    "process_import"]
