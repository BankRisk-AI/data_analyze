"""Lead-time utility (§3.6, H2).

Thin wrapper — the full implementation lives in domain.metrics.lead_time_quarters.
Kept here so evaluation code imports from a stable domain path.
"""
from app.modules.eba_ml.domain.metrics import lead_time_quarters  # noqa: F401
