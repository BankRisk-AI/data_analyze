from app.modules.eba_ingest.application.ingest_service import enqueue_import
from app.modules.eba_ingest.application.job_worker import ImportWorker
from app.core.worker import JobHandlerRegistry, Worker
from conftest import write_csv


def test_worker_claims_and_completes_pending_import(db):
    path = write_csv(db.dir / "tr_oth_worker.csv", [
        "AAAAAAAAAAAAAAAAAAAA,DE,202003,2020140,CET1 ratio,0.15,",
    ])
    import_id = enqueue_import([path], db.storage, schema=db.schema)
    calls = []
    registry = JobHandlerRegistry()
    registry.register("stage", lambda job, progress: calls.append(job.import_id))
    worker = Worker(registry, schema=db.schema, poll_interval=0)

    assert worker.process_one() is True
    assert calls == [import_id]
    db.cur.execute(
        "SELECT status, progress FROM job WHERE import_id = %s", (import_id,)
    )
    assert db.cur.fetchone() == ("completed", 100)
    db.cur.execute("SELECT status FROM import_batch WHERE import_id = %s", (import_id,))
    assert db.cur.fetchone()[0] == "uploaded"
    assert worker.process_one() is False


def test_worker_requeues_stale_processing_jobs(db):
    path = write_csv(db.dir / "tr_oth_stale.csv", [
        "AAAAAAAAAAAAAAAAAAAA,DE,202003,2020140,CET1 ratio,0.15,",
    ])
    import_id = enqueue_import([path], db.storage, schema=db.schema)
    db.cur.execute(
        """UPDATE job SET status = 'processing', started_at = now() - interval '1 hour'
           WHERE import_id = %s""",
        (import_id,),
    )
    assert ImportWorker(db.storage, db.schema, stale_after=60).recover_stale_jobs() == 1
    db.cur.execute("SELECT status FROM job WHERE import_id = %s", (import_id,))
    assert db.cur.fetchone()[0] == "pending"
