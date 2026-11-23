import pytest
from fastapi.testclient import TestClient
from app.modules.eba_ingest.presentation.api.api import create_app
from app.modules.eba_ingest.application.job_worker import ImportWorker
from conftest import write_csv
ROWS = ["AAAAAAAAAAAAAAAAAAAA,DE,202003,2020140,CET1 ratio,0.15,", "BBBBBBBBBBBBBBBBBBBB,FR,202003,2020140,CET1 ratio,0.12,",
        "AAAAAAAAAAAAAAAAAAAA,DE,202006,2020140,CET1 ratio,0.16,", "XXXXXXXXXXXXXXXXXXXX,OT,202003,2020140,CET1 ratio,0.50,"]

@pytest.fixture()
def client(db):
    app = create_app(db.storage, db.schema, max_bytes=5000)
    return TestClient(app)
def post(client, db, name="tr_oth_x.csv", rows=ROWS, **kw):
    p = write_csv(db.dir / name, rows)
    with open(p, "rb") as f: return client.post("/api/imports", files=[("files", (name, f, "text/csv"))], **kw)

def test_config(client):
    j = client.get("/api/config").json(); assert j["accepted_extensions"] == [".csv", ".xlsx"] and j["max_upload_mb"] > 0 and j["authentication"] is False

def test_upload_returns_the_report(client, db):
    r = post(client, db, data={"edition": "2020"}); assert r.status_code == 201
    j = r.json(); f = j["files"][0]
    assert j["status"] == "uploaded" and j["edition_label"] == "2020" and j["has_staging"] is False
    assert (j["job_status"], j["progress"], f["file_type"], f["recognised"]) == ("pending", 0, "tr_oth", None)
    worker = ImportWorker(db.storage, db.schema, poll_interval=0)
    worker.process_one()
    j = client.get(f"/api/imports/{j['import_id']}").json(); f = j["files"][0]
    assert (j["job_status"], j["progress"], j["has_staging"]) == ("completed", 100, True)
    assert (f["file_type"], f["recognised"], f["encoding"], f["rows"], f["aggregate_rows"]) == ("tr_oth", True, "utf-8", 4, 1)
    assert [(p["year"], p["quarter"], p["banks"], p["rows"]) for p in f["pairs"]] == [(2020, 1, 2, 2), (2020, 2, 1, 1)]

def test_list_and_detail_and_drop_staging(client, db):
    iid = post(client, db).json()["import_id"]
    lst = client.get("/api/imports").json(); assert lst[0]["import_id"] == iid and lst[0]["file_names"] == ["tr_oth_x.csv"] and lst[0]["has_staging"] is False
    ImportWorker(db.storage, db.schema, poll_interval=0).process_one()
    assert client.get(f"/api/imports/{iid}").json()["files"][0]["rows"] == 4
    assert client.delete(f"/api/imports/{iid}/staging").json() == {"dropped": 1}
    assert client.get(f"/api/imports/{iid}").json()["has_staging"] is False and client.get("/api/imports").json()[0]["has_staging"] is False

def test_drop_staging_is_blocked_while_job_is_pending(client, db):
    iid = post(client, db).json()["import_id"]
    response = client.delete(f"/api/imports/{iid}/staging")
    assert response.status_code == 409 and response.json()["type"] == "staging-in-use"
    ImportWorker(db.storage, db.schema, poll_interval=0).process_one()
    assert client.delete(f"/api/imports/{iid}/staging").status_code == 200

def test_problem_details_for_refusals(client, db):
    first = post(client, db).json()["import_id"]
    db.cur.execute("UPDATE import_batch SET status = 'loaded' WHERE import_id = %s", (first,))
    r = post(client, db); assert r.status_code == 409 and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == "duplicate-file" and "already loaded" in r.json()["detail"]
    big = post(client, db, name="tr_cre_big.csv", rows=["AAAAAAAAAAAAAAAAAAAA,DE,202003,2020140," + "x" * 60 + ",0.1,"] * 120)
    assert big.status_code == 413 and big.json()["type"] == "file-too-large"
    bad = post(client, db, name="tr_cre_x.csv", rows=["A,1,2,3,4,5,6,7,EXTRA,EXTRA"])
    assert bad.status_code == 201
    worker = ImportWorker(db.storage, db.schema, poll_interval=0)
    worker.process_one()
    worker.process_one()
    assert client.get(f"/api/imports/{bad.json()['import_id']}").json()["job_status"] == "failed"

def test_rejected_import_is_still_returned_and_listed(client, db):
    p = db.dir / "notes.csv"; p.write_text("a,b\n1,2\n")
    with open(p, "rb") as f: r = client.post("/api/imports", files=[("files", ("notes.csv", f, "text/csv"))])
    assert r.status_code == 201 and r.json()["status"] == "uploaded" and r.json()["job_status"] == "pending"
    ImportWorker(db.storage, db.schema, poll_interval=0).process_one()
    detail = client.get(f"/api/imports/{r.json()['import_id']}").json()
    assert detail["status"] == "rejected" and "no recognised" in detail["error"] and detail["has_staging"] is False
    assert client.get("/api/imports").json()[0]["status"] == "rejected"

def test_unknown_import_and_bad_request(client):
    r = client.get("/api/imports/999"); assert r.status_code == 404 and r.json()["type"] == "not-found"
    assert client.delete("/api/imports/999/staging").status_code == 404
    r = client.post("/api/imports"); assert r.status_code == 422 and r.json()["type"] == "invalid-request"
    assert client.get("/api/imports/abc").status_code == 422

def test_two_files_in_one_request_and_path_names_are_cleaned(client, db):
    a = write_csv(db.dir / "tr_oth_x.csv", ROWS); b = write_csv(db.dir / "tr_mrk_x.csv", ROWS[:2])
    with open(a, "rb") as fa, open(b, "rb") as fb:
        r = client.post("/api/imports", files=[("files", ("..\\..\\evil\\tr_oth_x.csv", fa, "text/csv")), ("files", ("tr_mrk_x.csv", fb, "text/csv"))])
    assert r.status_code == 201 and [f["name"] for f in r.json()["files"]] == ["tr_oth_x.csv", "tr_mrk_x.csv"]


def test_the_built_interface_is_served_with_client_side_routes(db, tmp_path):
    ui = tmp_path / "ui"; (ui / "assets").mkdir(parents=True); (ui / "index.html").write_text("<html>APP</html>"); (ui / "assets" / "a.js").write_text("console.log(1)")
    c = TestClient(create_app(db.storage, db.schema, ui_dir=str(ui)))
    assert c.get("/").text == "<html>APP</html>" and c.get("/imports").text == "<html>APP</html>" and c.get("/imports/3").text == "<html>APP</html>"   # SPA routes
    assert c.get("/assets/a.js").text == "console.log(1)"
    assert c.get("/api/imports").json() == [] and c.get("/api/imports/9").status_code == 404                                                       # the API still wins
