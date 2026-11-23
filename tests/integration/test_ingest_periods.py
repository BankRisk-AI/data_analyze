"""Regression: periods that are not YYYYMM must never make the period report fail (a cast placed after a regex in an AND is not protected)."""
import pytest

from app.modules.eba_ingest import enqueue_import, get_import, ingest, process_import
from app.modules.eba_ingest.infrastructure.storage import storage as storage_module
from app.core.worker import Worker
from app.worker import build_registry
from conftest import write_csv

GOOD = ["AAAAAAAAAAAAAAAAAAAA,DE,202003,I1,x,1,", "BBBBBBBBBBBBBBBBBBBB,FR,202003,I1,x,2,", "AAAAAAAAAAAAAAAAAAAA,DE,202006,I1,x,3,"]
ODD = ["AAAAAAAAAAAAAAAAAAAA,DE,2020,I1,x,4,", "AAAAAAAAAAAAAAAAAAAA,DE,202013,I1,x,5,", "AAAAAAAAAAAAAAAAAAAA,DE,,I1,x,6,", "AAAAAAAAAAAAAAAAAAAA,DE,abcdef,I1,x,7,", "AAAAAAAAAAAAAAAAAAAA,DE,202004,I1,x,8,"]


def test_odd_periods_give_warnings_not_errors(db):
    p = write_csv(db.dir / "tr_oth_odd.csv", GOOD + ODD)
    f = ingest([p], db.storage, schema=db.schema).files[0]
    assert f.recognised and f.rows == 8
    assert [(x.year, x.quarter, x.banks, x.rows) for x in f.pairs] == [(2020, 1, 2, 2), (2020, 2, 1, 2)]        # 202004 (April) counts in Q2; 202013 has no valid month and is left out
    assert "3 rows have a Period that is not YYYYMM" in f.warnings                                               # 2020, empty, abcdef
    assert "2 rows have a Period that is not a quarter end (the EBA files only have 03, 06, 09, 12)" in f.warnings   # 202004 and 202013


def test_worker_path_gives_the_same_report_as_the_synchronous_path(db):
    p = write_csv(db.dir / "tr_oth_same.csv", GOOD)
    sync = ingest([p], db.storage, schema=db.schema)
    db.cur.execute("UPDATE import_batch SET status = 'cancelled'")                       # so the same file can be queued again
    iid = enqueue_import([p], db.storage, schema=db.schema)
    Worker(build_registry(), schema=db.schema, poll_interval=0).process_one()
    got = get_import(iid, db.schema)
    strip = lambda f: {k: v for k, v in f.items() if k not in ("file_id", "staging_table", "seconds")}
    assert [strip(f) for f in got["files"]] == [strip(f) for f in sync.to_dict()["files"]]
    assert (got["status"], got["job_status"], got["progress"], got["has_staging"]) == ("uploaded", "completed", 100, True)


def test_the_worker_reads_the_registered_files_without_storing_or_hashing_them_again(db, monkeypatch):
    iid = enqueue_import([write_csv(db.dir / "tr_oth_once.csv", GOOD)], db.storage, schema=db.schema)
    monkeypatch.setattr(storage_module, "store", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the file was stored again")))
    assert process_import(iid, db.schema).status == "uploaded"


def test_files_are_not_inspected_until_the_worker_runs(db):
    iid = enqueue_import([write_csv(db.dir / "tr_oth_wait.csv", GOOD)], db.storage, schema=db.schema)
    f = get_import(iid, db.schema)["files"][0]
    assert f["recognised"] is None and f["file_type"] == "tr_oth"                    # unknown yet, not "not recognised"


def test_an_unreadable_file_rejects_the_import_and_fails_the_job(db):
    iid = enqueue_import([write_csv(db.dir / "tr_cre_bad.csv", ["A,DE,202003,1,x,1,,EXTRA"])], db.storage, schema=db.schema)
    Worker(build_registry(), schema=db.schema, poll_interval=0).process_one()
    got = get_import(iid, db.schema)
    assert (got["status"], got["job_status"]) == ("rejected", "failed") and "values, the header has" in got["error"] and got["has_staging"] is False
