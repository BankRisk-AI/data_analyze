from app.core.module import ModuleSpec
from app.modules.eba_processing.application.worker_handler import register_handlers
from app.modules.eba_processing.presentation.router import TAG, build_router

SPEC = ModuleSpec(
    name="eba_processing",
    description="Looks at the staged data (preview, profile, nulls, histogram, scatter) and validates it before it is inserted.",
    router_factory=build_router,
    register_handlers=register_handlers,
    migrations_dir=None,
    tags=[{"name": TAG, "description": "Preview, profile, null analysis, distribution and scatter charts, and validation of staged data."}],
)
