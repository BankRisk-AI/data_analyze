"""Load artefact + dataset + index arrays once, shared across all H* functions (§3.6).

Builds a RunContext from a results JSON directory and a live DB connection.
Labels are loaded from the stored rows in the artefact (saved by train.py);
T-2 will replace this with E2/E3 label functions once archived runs are superseded.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.modules.eba_ml.application.dataset import build_dataset


@dataclass
class RunContext:
    """All data needed to evaluate hypotheses for one training run."""
    artifact: dict[str, Any]
    dataset: dict[str, Any]
    rows: list[dict]
    keys: np.ndarray          # string key per row: "bank_id:period"
    key_index: dict[str, int] # reverse lookup
    target: str               # label name from artifact (metadata only in T-1)
    y: np.ndarray             # binary labels aligned to rows
    arrays: dict[str, np.ndarray]  # {model_name: OOF score array, nan where not OOF}
    valid: dict[str, np.ndarray]   # {model_name: bool mask of finite scores}
    selected: str             # name of best-OOF model
    period: np.ndarray        # ISO period strings aligned to rows
    run_dir: Path


def load_run_context(run_dir: str | Path, conn) -> RunContext:
    """Load artefact JSON + rebuild dataset; compute all index arrays.

    Labels are taken from the artefact's stored rows (field "label").
    Returns a RunContext ready for all hypothesis functions.
    """
    run = Path(run_dir)
    result_path = next(run.glob("results_*.json"))
    artifact = json.loads(result_path.read_text())

    dataset = build_dataset(conn, artifact.get("grid", "semiannual"), True)
    rows = dataset["rows"]
    keys = np.asarray([f"{r['bank_id']}:{r['period'].isoformat()}" for r in rows])
    key_index = {key: i for i, key in enumerate(keys)}

    target = artifact.get("target", "unknown")

    # Load labels from stored artefact rows
    stored_rows = artifact.get("rows", [])
    if stored_rows and "label" in stored_rows[0]:
        label_lookup = {
            (r["bank_id"], r["period"]): int(r["label"])
            for r in stored_rows
        }
        y = np.asarray(
            [label_lookup.get((row["bank_id"], row["period"].isoformat()), 0)
             for row in rows], dtype=int)
    else:
        raise NotImplementedError(
            "T-2: artefact has no stored row labels; E2/E3 label function required")

    predictions = artifact.get("predictions", {})
    arrays = {
        name: np.asarray([scores.get(key, np.nan) for key in keys], dtype=float)
        for name, scores in predictions.items()
    }
    valid = {name: np.isfinite(values) for name, values in arrays.items()}

    search = artifact.get("search", {})
    selected = max(
        ("LR", "RF", "XGB"),
        key=lambda name: max(search[name], key=lambda x: x["mean_pr_auc"])["mean_pr_auc"])

    period = np.asarray([r["period"].isoformat() for r in rows])

    return RunContext(
        artifact=artifact,
        dataset=dataset,
        rows=rows,
        keys=keys,
        key_index=key_index,
        target=target,
        y=y,
        arrays=arrays,
        valid=valid,
        selected=selected,
        period=period,
        run_dir=run,
    )
