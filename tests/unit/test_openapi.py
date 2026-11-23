"""docs/openapi.yaml is the contract with the client: it must be valid and exactly what the application generates."""
import json
from pathlib import Path

import pytest
import yaml
from openapi_spec_validator import validate

from app.main import create_app

FILE = Path(__file__).resolve().parents[2] / "docs" / "openapi.yaml"


def generated() -> dict:
    return json.loads(json.dumps(create_app(schema="public").openapi()))            # same normalisation as the file


def test_the_committed_file_is_up_to_date():
    assert FILE.is_file(), "run: make openapi"
    assert yaml.safe_load(FILE.read_text(encoding="utf-8")) == generated(), "docs/openapi.yaml is out of date: run `make openapi`"


def test_the_description_is_valid_openapi():
    validate(generated())


def test_every_operation_is_documented_for_clients():
    spec = generated()
    ids = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            ids.append(op["operationId"])
            assert op.get("summary") and op.get("tags"), f"{method.upper()} {path} lacks a summary or a tag"
            assert "200" in op["responses"] or "201" in op["responses"] or "202" in op["responses"]
    assert len(ids) == len(set(ids)) and not [i for i in ids if "_api_" in i], "operation ids must be explicit and unique"
    assert {t["name"] for t in spec["tags"]} == {"system", "ingest", "processing", "public-analysis", "ml"}


@pytest.mark.parametrize("path, method", [("/api/datasets/{file_id}/preview", "get"), ("/api/datasets/{file_id}/histogram", "get"), ("/api/datasets/{file_id}/scatter", "get"),
                                          ("/api/imports", "post"), ("/api/imports/{import_id}/validation", "post"), ("/api/imports/{import_id}", "get")])
def test_error_responses_are_declared_as_problem_json(path, method):
    op = generated()["paths"][path][method]
    errors = {k: v for k, v in op["responses"].items() if k.isdigit() and int(k) >= 400}
    assert errors, f"{method.upper()} {path} declares no error response"
    for status, response in errors.items():
        assert list(response["content"]) == ["application/problem+json"], f"{method.upper()} {path} {status} must be problem+json only"
        assert response["content"]["application/problem+json"]["schema"] == {"$ref": "#/components/schemas/Problem"}


def test_no_error_is_described_as_plain_json_and_the_default_validation_schemas_are_gone():
    spec = generated()
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            for status, response in op["responses"].items():
                if status.isdigit() and int(status) >= 400:
                    assert list(response["content"]) == ["application/problem+json"], f"{method.upper()} {path} {status}"
    assert "HTTPValidationError" not in spec["components"]["schemas"] and "Problem" in spec["components"]["schemas"]
