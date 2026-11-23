"""The processing API through the composed application (ingest + processing + system), and the whole pipeline from upload to validation."""
import pytest
from fastapi.testclient import TestClient

from app.core.worker import Worker
from app.main import create_app
from app.worker import build_registry
from helpers import banks, stage

AGG = ["XXXXXXXXXXXXXXXXXXXX,OT,202003,I1,Item one,0,5,"]


@pytest.fixture()
def client(db):
    return TestClient(create_app(schema=db.schema, storage_dir=db.storage, max_bytes=2_000_000))


@pytest.fixture()
def staged(db):
    return stage(db, banks(40) + AGG)


def problem(r, status, kind):
    assert r.status_code == status and r.headers["content-type"].startswith("application/problem+json"), r.text
    assert r.json()["type"] == kind and r.json()["status"] == status
    return r.json()


def test_config_lists_limits_enums_and_rules(client):
    j = client.get("/api/processing/config").json()
    assert (j["default_page_size"], j["max_page_size"], j["max_bins"], j["max_scatter_points"]) == (50, 1000, 200, 5000)
    assert j["aggregations"] == ["single", "sum", "mean", "min", "max"] and j["scales"] == ["linear", "log"] and j["clips"] == ["none", "p01-p99", "iqr"]
    assert [r["id"] for r in j["validation_rules"]] == [f"V{i:02d}" for i in range(1, 14)] and "dimension" in j["column_roles"]


def test_datasets_endpoints(client, db, staged):
    imp, fid = staged
    [d] = client.get(f"/api/imports/{imp}/datasets").json()
    assert d["file_id"] == fid and d["rows"] == 161 and d["periods"][0] == {"period": "202003", "year": 2020, "quarter": 1, "banks": 40, "rows": 80}
    assert client.get(f"/api/datasets/{fid}").json()["columns"][0] == {"name": "lei_code", "role": "key", "position": 1}
    problem(client.get("/api/imports/999/datasets"), 404, "not-found")
    problem(client.get("/api/datasets/999"), 404, "dataset-not-found")
    problem(client.get("/api/datasets/abc"), 422, "invalid-request")


def test_preview_endpoint(client, staged):
    _, fid = staged
    j = client.get(f"/api/datasets/{fid}/preview", params={"page_size": 5, "sort": "amount", "order": "desc", "period": "202003", "item": "I2", "exclude_aggregate": "true"}).json()
    assert (j["total"], j["pages"], len(j["rows"])) == (40, 8, 5) and [r["amount"] for r in j["rows"]] == ["60.0", "59.0", "58.0", "57.0", "56.0"]
    assert client.get(f"/api/datasets/{fid}/preview", params={"dim": ["portfolio:0", "nsa:DE"]}).json()["total"] == 160        # two dim filters combine; the aggregate row (nsa OT) is left out
    problem(client.get(f"/api/datasets/{fid}/preview", params={"sort": "amount; DROP TABLE job"}), 422, "invalid-parameter")
    problem(client.get(f"/api/datasets/{fid}/preview", params={"dim": "portfolio"}), 422, "invalid-parameter")
    problem(client.get(f"/api/datasets/{fid}/preview", params={"page_size": 5000}), 422, "invalid-request")
    problem(client.get(f"/api/datasets/{fid}/preview", params={"period": "2020"}), 422, "invalid-request")
    problem(client.get(f"/api/datasets/{fid}/preview", params={"order": "up"}), 422, "invalid-request")


def test_items_profile_nulls_endpoints(client, staged):
    _, fid = staged
    items = client.get(f"/api/datasets/{fid}/items", params={"q": "two"}).json()
    assert [i["item"] for i in items["items"]] == ["I2"] and items["pages"] == 1
    p = client.get(f"/api/datasets/{fid}/profile", params={"top": 3}).json()
    assert p["rows"] == 161 and {c["name"] for c in p["columns"]} >= {"amount", "footnote"} and p["amount"]["numeric"] == 161
    n = client.get(f"/api/datasets/{fid}/nulls", params={"by": "period", "columns": ["amount", "footnote"]}).json()
    assert n["columns"] == ["amount", "footnote"] and n["groups"][0]["null_pct"]["footnote"] == 100.0
    assert client.get(f"/api/datasets/{fid}/nulls", params={"by": "item"}).json()["groups"] == []
    problem(client.get(f"/api/datasets/{fid}/nulls", params={"by": "country"}), 422, "invalid-request")
    problem(client.get(f"/api/datasets/{fid}/profile", params={"top": 50}), 422, "invalid-request")


def test_histogram_and_scatter_endpoints(client, staged):
    _, fid = staged
    h = client.get(f"/api/datasets/{fid}/histogram", params={"item": "I1", "period": "202003", "bins": 4}).json()
    assert h["n"] == 40 and len(h["bins"]) == 4 and sum(b["count"] for b in h["bins"]) == 40 and h["stats"]["median"] == pytest.approx(19.75) and h["label"] == "Item one"
    problem(client.get(f"/api/datasets/{fid}/histogram"), 422, "invalid-request")                         # item is required
    problem(client.get(f"/api/datasets/{fid}/histogram", params={"item": "I1", "scale": "sqrt"}), 422, "invalid-request")
    problem(client.get(f"/api/datasets/{fid}/histogram", params={"item": "I1", "bins": 500}), 422, "invalid-request")
    s = client.get(f"/api/datasets/{fid}/scatter", params={"x_item": "I1", "y_item": "I2", "x_period": "202003", "y_period": "202003", "max_points": 20}).json()
    assert (s["n_pairs"], len(s["points"]), s["sampled"], s["agg"]) == (40, 20, True, "single") and s["stats"]["pearson"] == pytest.approx(1.0) and s["x"]["label"] == "Item one"
    problem(client.get(f"/api/datasets/{fid}/scatter", params={"x_item": "I1", "y_item": "I2", "x_period": "202003"}), 422, "invalid-request")
    problem(client.get(f"/api/datasets/{fid}/scatter", params={"x_item": "I1", "y_item": "I2", "x_period": "202003", "y_period": "202003", "agg": "median"}), 422, "invalid-request")


def test_a_dropped_staging_gives_404_everywhere_never_500(client, staged):
    imp, fid = staged
    assert client.delete(f"/api/imports/{imp}/staging").json() == {"dropped": 1}
    assert client.get(f"/api/imports/{imp}/datasets").json() == []
    for path, params in [("", {}), ("/preview", {}), ("/items", {}), ("/profile", {}), ("/nulls", {}), ("/histogram", {"item": "I1"}),
                         ("/scatter", {"x_item": "I1", "y_item": "I2", "x_period": "202003", "y_period": "202003"})]:
        problem(client.get(f"/api/datasets/{fid}{path}", params=params), 404, "dataset-not-found")
    problem(client.post(f"/api/imports/{imp}/validation"), 409, "no-staging")


def test_a_slow_query_becomes_a_504_problem(client, staged, monkeypatch):
    import app.modules.eba_processing.application.session as session
    import app.modules.eba_processing.infrastructure.sql_analytics as infra
    monkeypatch.setattr(session, "QUERY_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(infra, "profile", lambda cur, *a, **k: cur.execute("SELECT pg_sleep(3)"))
    body = problem(client.get(f"/api/datasets/{staged[1]}/profile"), 504, "query-too-slow")
    assert "more than 1 s" in body["detail"]


def test_unexpected_errors_do_not_leak_details(db, staged, monkeypatch):
    import app.modules.eba_processing.infrastructure.sql_analytics as infra
    monkeypatch.setattr(infra, "profile", lambda *a, **k: 1 / 0)
    r = TestClient(create_app(schema=db.schema, storage_dir=db.storage), raise_server_exceptions=False).get(f"/api/datasets/{staged[1]}/profile")
    body = problem(r, 500, "internal-error")
    assert "division" not in r.text and "ZeroDivision" not in r.text and "server log" in body["detail"]


def test_request_id_is_returned_and_echoed(client):
    assert len(client.get("/api/config").headers["x-request-id"]) == 12
    assert client.get("/api/config", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"


# ----------------------------------------------------------------------------------- system endpoints
def test_health_reports_database_queue_and_a_missing_worker(client, db):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["database"] is True and h["modules"] == ["eba_ingest", "eba_processing", "eba_public_analysis", "eba_ml"] and h["queue"]["pending"] == 0 and h["worker_hint"] is None
    imp, _ = stage(db, banks(3))
    db.cur.execute("INSERT INTO job(import_id, kind, status) VALUES (%s, 'validate_data', 'pending')", (imp,))
    assert client.get("/api/health").json()["worker_hint"] is None                     # waiting for a few seconds is normal
    db.cur.execute("UPDATE job SET created_at = now() - interval '2 minutes' WHERE status = 'pending'")
    h = client.get("/api/health").json()
    assert h["status"] == "degraded" and "start the worker" in h["worker_hint"] and h["queue"]["pending"] == 1 and h["queue"]["oldest_pending_seconds"] > 100


def test_meta_lists_enums_and_every_problem_type(client):
    m = client.get("/api/meta").json()
    assert m["job_statuses"] == ["pending", "processing", "completed", "failed"] and "validated" in m["import_statuses"] and "unrecognised" in m["file_types"]
    assert set(m["job_kinds"]) == {"stage", "validate_data", "load", "evaluate_rules",
                                    "build_ml_dataset", "train_model", "tune_model",
                                    "evaluate_model", "score_panel"}
    types = {p["type"]: p["status"] for p in m["problem_types"]}
    assert types["duplicate-file"] == 409 and types["file-too-large"] == 413 and types["unreadable-file"] == 422 and types["dataset-not-found"] == 404
    assert types["no-staging"] == 409 and types["query-too-slow"] == 504 and types["invalid-parameter"] == 422 and types["internal-error"] == 500 and types["invalid-request"] == 422


def test_job_endpoints(client, db, staged):
    imp, _ = staged
    q = client.post(f"/api/imports/{imp}/validation")
    assert q.status_code == 202 and q.json()["created"] is True
    jobs = client.get(f"/api/imports/{imp}/jobs").json()
    assert [j["kind"] for j in jobs] == ["validate_data", "stage"] and jobs[0]["status"] == "pending"
    one = client.get(f"/api/jobs/{q.json()['job_id']}").json()
    assert one["import_id"] == imp and one["progress"] == 0 and one["finished_at"] is None
    problem(client.get("/api/jobs/9999"), 404, "not-found")
    assert client.get("/api/imports/9999/jobs").json() == []


# ------------------------------------------------------------------------------------ the whole pipeline
def test_upload_process_and_validate_through_the_api(client, db):
    csv = ("LEI_Code,NSA,Period,Item,Label,Portfolio,Amount,footnote\n" + "\n".join(banks(40)) + "\n").encode("cp1252")
    r = client.post("/api/imports", files=[("files", ("tr_cre_pipeline.csv", csv, "text/csv"))], data={"edition": "2020"})
    assert r.status_code == 201 and r.json()["job_status"] == "pending" and r.json()["files"][0]["recognised"] is None
    imp = r.json()["import_id"]
    assert client.get(f"/api/imports/{imp}/datasets").json() == []                       # nothing staged until the worker has run
    worker = Worker(build_registry(), schema=db.schema, poll_interval=0)
    assert worker.process_one() is True
    done = client.get(f"/api/imports/{imp}").json()
    assert (done["job_status"], done["progress"], done["has_staging"], done["status"]) == ("completed", 100, True, "uploaded") and done["files"][0]["recognised"] is True
    [d] = client.get(f"/api/imports/{imp}/datasets").json()
    assert d["rows"] == 160
    assert client.get(f"/api/imports/{imp}/validation").json() == {"import_id": imp, "import_status": "uploaded", "job": None, "report": None}
    assert client.post(f"/api/imports/{imp}/validation").status_code == 202
    assert worker.process_one() is True
    v = client.get(f"/api/imports/{imp}/validation").json()
    assert v["job"]["status"] == "completed" and v["import_status"] == "validated"
    assert v["report"]["summary"] == {"errors": 0, "warnings": 0, "infos": 0, "can_proceed": True}
    assert [i["rule"] for i in v["report"]["files"][0]["issues"]] == [f"V{i:02d}" for i in range(1, 14)] and worker.process_one() is False


def test_the_module_command_line_validates_without_the_worker(db, capsys, monkeypatch):
    from app.modules.eba_processing.__main__ import main

    imp, _ = stage(db, banks(40) + ["SHORTLEI,DE,202003,I1,Item one,0,1,"])
    monkeypatch.setenv("EBA_SCHEMA", db.schema)
    assert main(["validate", str(imp)]) == 3                                            # an error was found: exit code 3
    out = capsys.readouterr().out
    assert "1 errors" in out and "V07 error" in out and "cannot proceed" in out
    assert main(["validate", "9999"]) == 2
    assert main(["config"]) == 0 and "validation_rules" in capsys.readouterr().out
