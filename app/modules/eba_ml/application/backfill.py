"""Stage 5c protected-model backfill — superseded by T-2.

This script was used once to import Stage 5c XGB/RF/LR models trained on T5
into the registry. The models are already in the database as protected rows.
Running this again would overwrite them; do not run it.
"""


def backfill_protected_models(result_path="data/ml/results_T5_semiannual_robust.json"):
    raise NotImplementedError(
        "backfill_protected_models is superseded. "
        "Protected Stage 5c models are already in the registry. "
        "T-2 will register models trained on E2/E3 labels."
    )
