"""Deprecated re-export shim for pipeline.train and pipeline.hypotheses.

Existing imports from this module continue to work.
New code should import from:
  app.modules.eba_ml.application.training.train
  app.modules.eba_ml.application.evaluation.hypotheses
"""
import warnings as _warnings

from app.modules.eba_ml.application.training.train import (  # noqa: F401
    train,
    fit_final_model,
    EU_EBA_V1_1_PROFILE_SHA,
)
from app.modules.eba_ml.application.evaluation.hypotheses import (  # noqa: F401
    hypotheses,
)
from app.modules.eba_ml.application.models import SEED, SEARCH_CONFIGURATIONS  # noqa: F401

_warnings.warn(
    "app.modules.eba_ml.application.pipeline is deprecated; "
    "import from training.train or evaluation.hypotheses instead.",
    DeprecationWarning,
    stacklevel=2,
)
