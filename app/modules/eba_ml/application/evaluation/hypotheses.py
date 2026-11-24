"""Hypotheses evaluation orchestrator for eba_ml (§3.6).

Recipe: load_run_context -> H1a -> H1b -> H2 -> H3 -> H5 -> save.
Each step is a named function call; no logic lives here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.modules.eba_ml.application.models import SEARCH_CONFIGURATIONS
from app.modules.eba_ml.application.io import get_logger, write_json
from app.modules.eba_ml.application.evaluation.context import load_run_context
from app.modules.eba_ml.application.evaluation.h1a import compute_h1a
from app.modules.eba_ml.application.evaluation.h1b import compute_h1b
from app.modules.eba_ml.application.evaluation.h2 import compute_h2
from app.modules.eba_ml.application.evaluation.h3 import compute_h3
from app.modules.eba_ml.application.evaluation.h5 import compute_h5


def hypotheses(run_dir: str | Path, seed: int | None = None,
               quick: bool = False) -> dict[str, Any]:
    """Evaluate all hypotheses for a training run and save hypotheses.json (§3.6).

    Steps: load_run_context -> H1a -> H1b -> H2 -> H3 -> H5 -> save.
    """
    from app.core.config import get_schema
    from app.core.database import connect
    from app.modules.eba_ml.application.models import SEED as _SEED

    if seed is None:
        seed = _SEED
    replicates, h3_budget, loeo_limit = (20, 2, 1) if quick else (2000, SEARCH_CONFIGURATIONS, None)
    logger = get_logger()
    logger.info("hypotheses run=%s", run_dir)

    conn = connect(get_schema())
    try:
        ctx = load_run_context(run_dir, conn)
        h1 = compute_h1a(ctx, seed, replicates)
        h1b = compute_h1b(ctx, conn)
        h2 = compute_h2(ctx, conn, loeo_limit)
        h3 = compute_h3(ctx, seed, replicates, h3_budget)
        h5 = compute_h5(ctx)

        report = {
            "run": str(run_dir),
            "selected_model": ctx.selected,
            "H1a": h1,
            "H1b": h1b,
            "H2": h2,
            "H3": h3,
            "H4": {"status": "pending - Stage 7 (BNM pilot)"},
            "H5": h5,
        }

        write_json(Path(run_dir) / "hypotheses.json", report)
        logger.info("run finished")
        return report
    finally:
        conn.close()
