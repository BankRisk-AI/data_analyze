import pytest

from app.core.worker import Worker
from app.modules.eba_ingest import drop_staging
from app.modules.eba_ingest.application.queries import StagingInUse
from app.modules.eba_processing.application import validation as V
from app.modules.eba_processing.application.validation import NothingToValidate, report_to_dict
from app.worker import build_registry
from helpers import banks, stage

BAD = [
    "LEI00000000000000999,DE,202003,I1,Item one,0,10000,",   # outlier, and a 41st bank in 202003
    "LEI00000000000000000,DE,202006,I2,Item two,0,25.0,",    # the same identity as an existing row: duplicate
    "LEI00000000000000101,DE,202003,I3,Three,0,abc,",        # not a number
    "LEI00000000000000102,DE,202003,I3,Three,0,,",           # empty amount
    "LEI00000000000000103,DE,2020,I3,Three,0,1,",            # period not YYYYMM
    "LEI00000000000000104,DE,202013,I3,Three,0,1,",          # month 13
    "LEI00000000000000105,DE,202004,I3,Three,0,1,",          # not a quarter end
    "SHORTLEI,DE,202003,I3,Three,0,1,",                      # LEI is not 20 characters
    "LEI00000000000000106,de,202003,I3,Three,0,1,",          # country not upper-case
    "LEI00000000000000107,DE,202003,I3,Three b,0,1,",        # a second label for I3
    "LEI00000000000000108,DE,202003,,Three,0,1,",            # no item
    "XXXXXXXXXXXXXXXXXXXX,OT,202003,I1,Item one,0,5,", "XXXXXXXXXXXXXXXXXXXX,OT,202006,I1,Item one,0,5,",   # the aggregate bucket
]


def issues(rep, file=0):
    return {i["rule"]: i for i in report_to_dict(rep)["files"][file]["issues"]}


def test_every_rule_finds_exactly_what_was_planted(db):
    imp, _ = stage(db, banks(40) + BAD)
    rep = V.run_validation(imp, db.schema)
    i = issues(rep)
    failed = {k for k, v in i.items() if v["status"] == "failed"}
    assert failed == {"V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10", "V11", "V12"} and i["V13"]["status"] == "passed"
    assert i["V01"]["affected_rows"] == 1 and i["V01"]["examples"][0]["lei_code"] == "LEI00000000000000108"
    assert i["V02"]["affected_rows"] == 2 and "conflicting amounts" in i["V02"]["detail"] and i["V02"]["examples"][0]["copies"] == 2
    assert i["V03"]["affected_rows"] == 1 and i["V03"]["examples"][0]["amount"] == "abc"
    assert i["V04"]["affected_rows"] == 1
    assert i["V05"]["affected_rows"] == 2 and {e["period"] for e in i["V05"]["examples"]} == {"2020", "202013"}
    assert i["V06"]["affected_rows"] == 1 and i["V06"]["examples"][0]["period"] == "202004"
    assert i["V07"]["affected_rows"] == 1 and i["V07"]["examples"][0]["lei_code"] == "SHORTLEI"           # the aggregate bucket is exempt
    assert i["V08"]["affected_rows"] == 1 and i["V08"]["examples"][0]["nsa"] == "de"
    assert i["V09"]["affected_rows"] == 8 and i["V09"]["examples"][0] == {"item": "I3", "labels": ["Three", "Three b"]}
    assert i["V11"]["affected_rows"] == 1 and i["V11"]["examples"][0]["lei_code"] == "LEI00000000000000999"
    assert i["V12"]["affected_rows"] == 2
    assert i["V10"]["examples"][0]["period"] == "202003" and "202003: " in i["V10"]["detail"]
    sev = {k: v["severity"] for k, v in i.items()}
    assert (rep.errors, rep.warnings, rep.infos) == (5, 4, 3) and sev["V02"] == "error" and sev["V09"] == "warning" and sev["V11"] == "info" and not rep.can_proceed
    assert all(len(v["examples"]) <= 5 for v in i.values())

def test_exact_duplicate_is_informational(db):
    rows = banks(2)
    rows.append(rows[0])
    imp, _ = stage(db, rows)
    issue = issues(V.run_validation(imp, db.schema))["V02"]
    assert issue["severity"] == "info" and issue["affected_rows"] == 2


def test_status_follows_the_result_and_the_report_is_stored(db):
    imp, fid = stage(db, banks(40))
    status = lambda: (db.cur.execute("SELECT status FROM import_batch WHERE import_id = %s", (imp,)), db.cur.fetchone()[0])[1]
    assert status() == "uploaded"
    clean = V.run_validation(imp, db.schema)
    assert clean.can_proceed and (clean.errors, clean.warnings, clean.infos) == (0, 0, 0) and status() == "validated"
    db.cur.execute("INSERT INTO staging.f%s VALUES ('SHORTLEI','DE','202003','I1','Item one','0','1',NULL)" % fid)     # a new problem appears
    again = V.run_validation(imp, db.schema)
    assert not again.can_proceed and status() == "uploaded"                                                      # validated -> uploaded
    db.cur.execute("UPDATE import_batch SET status = 'loaded' WHERE import_id = %s", (imp,))
    V.run_validation(imp, db.schema)
    assert status() == "loaded"                                                                                  # never touches later states
    db.cur.execute("SELECT count(*) FROM decision_log WHERE import_id = %s AND step = 'validation_report'", (imp,)); assert db.cur.fetchone()[0] == 3
    state = V.get_validation(imp, db.schema)
    assert state["report"]["summary"] == {"errors": 1, "warnings": 0, "infos": 1, "can_proceed": False} and state["import_status"] == "loaded"


def test_an_empty_dimension_column_is_reported(db):
    rows = [r.replace(",0,", ",,", 1) for r in banks(5)]
    imp, _ = stage(db, rows)
    i = issues(V.run_validation(imp, db.schema))
    assert i["V13"]["status"] == "failed" and i["V13"]["examples"] == [{"column": "portfolio"}] and "footnote" not in i["V13"]["detail"]


def test_nothing_to_validate_without_staging_tables(db):
    imp, _ = stage(db, banks(5))
    drop_staging(imp, db.schema)
    with pytest.raises(NothingToValidate): V.run_validation(imp, db.schema)
    with pytest.raises(NothingToValidate): V.enqueue_validation(imp, db.schema)


def test_the_worker_runs_the_validation_job_with_progress(db):
    imp, _ = stage(db, banks(40))
    q = V.enqueue_validation(imp, db.schema)
    assert q["created"] is True and q["status"] == "pending"
    assert V.enqueue_validation(imp, db.schema) == {"job_id": q["job_id"], "status": "pending", "created": False}      # idempotent while waiting
    before = V.get_validation(imp, db.schema)
    assert before["job"]["status"] == "pending" and before["report"] is None
    worker = Worker(build_registry(), schema=db.schema, poll_interval=0)
    assert worker.process_one() is True
    after = V.get_validation(imp, db.schema)
    assert (after["job"]["status"], after["job"]["progress"]) == ("completed", 100) and after["report"]["summary"]["can_proceed"] is True and after["import_status"] == "validated"
    assert V.enqueue_validation(imp, db.schema)["created"] is True                                                   # a new run is allowed once the first finished


def test_a_failing_validation_marks_the_job_failed(db):
    imp, _ = stage(db, banks(5))
    q = V.enqueue_validation(imp, db.schema)
    with pytest.raises(StagingInUse):
        drop_staging(imp, db.schema)
    db.cur.execute("UPDATE job SET status='completed' WHERE job_id=%s", (q["job_id"],))
    drop_staging(imp, db.schema)                                                                                      # the data disappear before the worker runs
    db.cur.execute("UPDATE job SET status='pending' WHERE job_id=%s", (q["job_id"],))
    Worker(build_registry(), schema=db.schema, poll_interval=0).process_one()
    st = V.get_validation(imp, db.schema)
    assert st["job"]["job_id"] == q["job_id"] and st["job"]["status"] == "failed" and "no staging tables" in st["job"]["error"] and st["report"] is None
