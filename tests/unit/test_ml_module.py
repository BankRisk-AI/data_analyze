import hashlib
import json
from pathlib import Path

import pytest

from app.modules.eba_ml.application import lifecycle
from app.modules.eba_ml.application.lifecycle import can_delete
from app.modules.eba_ml.domain.exceptions import ProtectedModelError
from app.core.exceptions import InvalidParameter
from app.modules.eba_ml.infrastructure.artifacts import ArtifactStore
from app.modules.eba_ml.application.models import _search_configs


def test_artifact_store_verifies_sha(tmp_path):
    store = ArtifactStore(tmp_path)
    payload = b"deterministic model"
    sha = store.put(payload, {"data_hash": "0" * 64})
    assert sha == hashlib.sha256(payload).hexdigest()
    assert store.load(sha) == payload
    (tmp_path / "models" / sha / "model.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="verification"):
        store.load(sha)


def test_artifact_store_round_trips_joblib_model(tmp_path):
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression().fit([[0], [1]], [0, 1])
    import io
    import joblib
    payload = io.BytesIO()
    joblib.dump(model, payload)
    store = ArtifactStore(tmp_path)
    sha = store.put(payload.getvalue(), {"format": "joblib"})
    loaded = store.load_model(sha, "joblib")
    assert loaded.predict([[0], [1]]).tolist() == [0, 1]


def test_search_configurations_are_deterministic_and_complete():
    for algorithm in ("LR", "RF", "XGB"):
        first = _search_configs(algorithm)
        assert len(first) == 60
        assert first == _search_configs(algorithm)


def test_protected_and_champion_models_cannot_be_deleted():
    with pytest.raises(ProtectedModelError):
        can_delete({"name": "protected", "protected": True,
                    "status": "validated"}, "protected")
    with pytest.raises(ProtectedModelError):
        can_delete({"name": "champion", "protected": False,
                    "status": "champion"}, "champion")
    with pytest.raises(InvalidParameter, match="exact model name"):
        can_delete({"name": "m", "protected": False,
                    "status": "validated"}, "M")


def test_list_predictions_returns_correct_shape(monkeypatch):
    from contextlib import contextmanager
    from app.modules.eba_ml.application import service

    class FakeCursor:
        description = [("prediction_id",), ("bank_id",), ("probability",)]
        def execute(self, *_): pass
        def fetchall(self): return [(1, 10, 0.75), (2, 11, 0.42)]
        def __enter__(self): return self
        def __exit__(self, *_): pass

    class FakeConn:
        def cursor(self): return FakeCursor()
        def __enter__(self): return self
        def __exit__(self, *_): pass

    @contextmanager
    def fake_connect(_schema):
        yield FakeConn()

    monkeypatch.setattr(service, "connect", fake_connect)

    result = service.list_predictions(page=1, page_size=50, champion_only=False)
    assert result["page"] == 1
    assert result["page_size"] == 50
    assert len(result["items"]) == 2
    assert result["items"][0] == {"prediction_id": 1, "bank_id": 10, "probability": 0.75}
    assert "total" not in result


def test_list_predictions_champion_only_passes_where_clause(monkeypatch):
    from contextlib import contextmanager
    from app.modules.eba_ml.application import service

    captured = {}

    class FakeCursor:
        description = [("prediction_id",)]
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
        def fetchall(self): return []
        def __enter__(self): return self
        def __exit__(self, *_): pass

    class FakeConn:
        def cursor(self): return FakeCursor()
        def __enter__(self): return self
        def __exit__(self, *_): pass

    @contextmanager
    def fake_connect(_schema):
        yield FakeConn()

    monkeypatch.setattr(service, "connect", fake_connect)

    service.list_predictions(1, 50, champion_only=True)
    assert "status='champion'" in captured["sql"]

    service.list_predictions(1, 50, champion_only=False)
    assert "champion" not in captured["sql"]


def test_thesis_headline_regression_numbers():
    path = Path("data/ml/results_T5_semiannual_robust.json")
    if not path.exists():
        pytest.skip("thesis artefact is not checked out")
    result = json.loads(path.read_text())
    if "search" not in result:
        pytest.skip("pre-redo result is not a Stage 5b-R artefact")
    assert set(result["pooled_metrics"]) >= {"LR", "RF", "XGB", "v1.1 score", "B4", "B2"}
    assert all(len(value) == 2 for value in result["bootstrap_cis"].values())
    assert result["search_configurations"] == 60
    assert all(len(result["search"][model]) == 60 for model in ("LR", "RF", "XGB"))
