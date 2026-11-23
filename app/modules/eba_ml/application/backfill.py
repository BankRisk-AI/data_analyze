from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

import numpy as np

from app.core.database import connect
from app.core.config import get_schema
from app.modules.eba_ml.application.dataset import build_dataset, folds
from app.modules.eba_ml.application.models import model_factory
from app.modules.eba_ml.infrastructure.artifacts import ArtifactStore


def _serialise(model, algorithm: str) -> tuple[bytes, str]:
    if algorithm == "XGB":
        with tempfile.NamedTemporaryFile(suffix=".json") as handle:
            model.save_model(handle.name)
            handle.seek(0)
            return handle.read(), "xgboost_json"
    import joblib
    handle = io.BytesIO()
    joblib.dump(model, handle)
    return handle.getvalue(), "joblib"


def backfill_protected_models(result_path="data/ml/results_T5_semiannual_robust.json"):
    result = json.loads(Path(result_path).read_text())
    with connect(get_schema()) as conn:
        dataset = build_dataset(conn, "semiannual", True)
        actual = np.asarray([(row["bank_id"], row["period"]) in dataset["targets"]["T5"]
                             for row in dataset["rows"]], dtype=int)
        store = ArtifactStore()
        reports = []
        for algorithm in ("LR", "RF", "XGB"):
            model = model_factory()[algorithm]
            max_diff = 0.0
            for train_idx, test_idx in folds(dataset["rows"]):
                if not len(train_idx) or not len(test_idx):
                    continue
                model.fit(dataset["X"][train_idx], actual[train_idx])
                observed = model.predict_proba(dataset["X"][test_idx])[:, 1]
                for index, probability in zip(test_idx, observed):
                    key = f"{dataset['rows'][index]['bank_id']}:{dataset['rows'][index]['period'].isoformat()}"
                    if key in result["predictions"].get(algorithm, {}):
                        max_diff = max(max_diff, abs(float(probability) -
                                                     result["predictions"][algorithm][key]))
            model.fit(dataset["X"][[i for i, row in enumerate(dataset["rows"])
                                    if row["period"].year <= 2020]],
                      actual[[i for i, row in enumerate(dataset["rows"])
                              if row["period"].year <= 2020]])
            payload, format_name = _serialise(model, algorithm)
            card = {"format": format_name, "algorithm": algorithm,
                    "data_hash": dataset["panel_hash"], "config": result["target"],
                    "metrics": result["pooled_metrics"], "columns": dataset["columns"],
                    "max_oof_abs_diff": max_diff}
            sha = store.put(payload, card)
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""UPDATE ml_model SET artifact_sha256=%s,model_card=%s
                                   WHERE name=%s AND protected=true""",
                                (sha, json.dumps(card),
                                 f"stage5c-robustness-{algorithm.lower()}"))
                    cur.execute("""INSERT INTO audit_log(action,entity,entity_id,detail)
                                   SELECT 'protected artefact backfill','ml_model',model_id,%s
                                   FROM ml_model WHERE name=%s""",
                                (json.dumps({"max_abs_diff": max_diff, "sha256": sha}),
                                 f"stage5c-robustness-{algorithm.lower()}"))
            reports.append({"algorithm": algorithm, "sha256": sha,
                            "max_abs_diff": max_diff})
        return reports
