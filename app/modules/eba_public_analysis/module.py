from app.core.module import ModuleSpec
from app.modules.eba_public_analysis.presentation.router import TAG, build_router

SPEC = ModuleSpec(
    name="eba_public_analysis",
    description="Reads promoted Chapter 4 data and exposes preview, profiles, charts and extensible aggregations.",
    router_factory=build_router,
    register_handlers=None,
    migrations_dir=None,
    tags=[{"name": TAG, "description": "Analysis and chart-ready data from public facts and mirror views."}],
)
