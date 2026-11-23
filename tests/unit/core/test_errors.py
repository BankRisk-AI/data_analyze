from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.api import create_base_app
from app.core.exceptions import AppError, InvalidParameter, NotFoundError


class Teapot(AppError):
    kind = "teapot"
    status = 418
    title = "I am a teapot"


def app_with_routes():
    app = create_base_app("t", "t")
    r = APIRouter()

    @r.get("/teapot")
    def teapot(): raise Teapot("short and stout")
    @r.get("/missing")
    def missing(): raise NotFoundError("no such thing")
    @r.get("/bad")
    def bad(): raise InvalidParameter("nope")
    @r.get("/crash")
    def crash(): raise RuntimeError("secret internal detail")
    @r.get("/int/{n}")
    def integer(n: int): return n
    app.include_router(r)
    return TestClient(app, raise_server_exceptions=False)


def test_every_app_error_becomes_problem_json_with_its_own_status():
    c = app_with_routes()
    for path, status, kind, title in [("/teapot", 418, "teapot", "I am a teapot"), ("/missing", 404, "not-found", "Not found"), ("/bad", 422, "invalid-parameter", "Invalid parameter")]:
        r = c.get(path)
        assert r.status_code == status and r.headers["content-type"].startswith("application/problem+json")
        assert (r.json()["type"], r.json()["title"], r.json()["status"]) == (kind, title, status)
        assert r.json()["code"] == kind and r.json()["message"] == title and r.json()["request_id"]
    assert c.get("/teapot").json()["detail"] == "short and stout"


def test_validation_errors_list_the_offending_parameter_and_crashes_leak_nothing():
    c = app_with_routes()
    r = c.get("/int/abc")
    assert r.status_code == 422 and r.json()["type"] == "invalid-request" and "n" in r.json()["detail"]
    r = c.get("/crash")
    assert r.status_code == 500 and r.json()["type"] == "internal-error" and "secret" not in r.text
    assert r.json()["code"] == "internal-error" and r.json()["request_id"]
    assert c.get("/nope").json()["type"] == "not-found"                                   # unknown routes are problem+json too


def test_request_id_is_correlated_in_response_and_error_envelope():
    c = app_with_routes()
    r = c.get("/crash", headers={"X-Request-ID": "frontend-request-1"})
    assert r.headers["X-Request-ID"] == "frontend-request-1"
    assert r.json()["request_id"] == "frontend-request-1"
