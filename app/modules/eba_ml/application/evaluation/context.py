"""Load artefact + dataset + index arrays once, shared across all H* functions (§3.6).

Builds a RunContext from a results JSON directory and a live DB connection.
Labels are loaded from the stored rows in the artefact; panel_hash verified.
"""
from __future__ import annotations

import json
import warnings
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
    keys: np.ndarray
    key_index: dict[str, int]
    target: str
    y: np.ndarray
    arrays: dict[str, np.ndarray]
    valid: dict[str, np.ndarray]
    selected: str
    period: np.ndarray
    operating_point_threshold: float
    r1_margin: float
    run_dir: Path
    conn: Any  # live DB connection (for H1b v1.1 query)


def load_run_context(run_dir: str | Path, conn) -> RunContext:
    """Load artefact JSON + rebuild dataset; compute all index arrays."""
    run = Path(run_dir)
    result_path = next(run.glob("results_*.json"))
    artifact = json.loads(result_path.read_text())

    dataset = build_dataset(conn, artifact.get("grid", "semiannual"),
                            artifact.get("robustness", True))

    stored_hash = artifact.get("panel_hash")
    if stored_hash and stored_hash != dataset["panel_hash"]:
        warnings.warn(
            f"panel_hash mismatch: stored={stored_hash[:12]}... "
            f"live={dataset['panel_hash'][:12]}...; results may not match live panel",
            stacklevel=2)

    rows = dataset["rows"]
    keys = np.asarray([f"{r['bank_id']}:{r['period'].isoformat()}" for r in rows])
    key_index = {k: i for i, k in enumerate(keys)}

    target = artifact.get("label", artifact.get("target", "unknown"))

    stored_rows = artifact.get("rows", [])
    if stored_rows and "label" in stored_rows[0]:
        label_lookup = {(r["bank_id"], r["period"]): int(r["label"]) for r in stored_rows}
        y = np.asarray(
            [label_lookup.get((row["bank_id"], row["period"].isoformat()), -1)
             for row in rows], dtype=int)
    else:
        raise NotImplementedError("artefact has no stored row labels; run train() first")

    predictions = artifact.get("predictions", {})
    arrays = {
        name: np.asarray([scores.get(key, np.nan) for key in keys], dtype=float)
        for name, scores in predictions.items()
    }
    valid = {name: np.isfinite(v) & (y >= 0) for name, v in arrays.items()}

    selected = artifact.get("selected_model") or max(
        ("LR", "RF", "XGB"),
        key=lambda n: max(artifact.get("search", {}).get(n, [{"mean_pr_auc": 0}]),
                          key=lambda x: x["mean_pr_auc"])["mean_pr_auc"])

    period = np.asarray([r["period"].isoformat() for r in rows])
    op_threshold = float(artifact.get("operating_point_threshold", 0.5))
    r1_margin = float(artifact.get("r1_margin", 0.0))

    return RunContext(
        artifact=artifact, dataset=dataset, rows=rows, keys=keys, key_index=key_index,
        target=target, y=y, arrays=arrays, valid=valid, selected=selected,
        period=period, operating_point_threshold=op_threshold, r1_margin=r1_margin,
        run_dir=run, conn=conn,
    )
