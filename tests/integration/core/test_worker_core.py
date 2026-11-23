import threading
import time

from app.core.worker import JobHandlerRegistry, Worker


def new_job(db, kind="demo"):
    db.cur.execute("INSERT INTO import_batch(status) VALUES ('uploaded') RETURNING import_id")
    iid = db.cur.fetchone()[0]
    db.cur.execute("INSERT INTO job(import_id, kind) VALUES (%s, %s) RETURNING job_id", (iid, kind))
    return iid, db.cur.fetchone()[0]


def row(db, jid, cols="status, progress, message, error"):
    db.cur.execute(f"SELECT {cols} FROM job WHERE job_id = %s", (jid,))
    return db.cur.fetchone()


def test_handlers_receive_the_schema_the_worker_runs_on(db):
    seen = []
    reg = JobHandlerRegistry(); reg.register("demo", lambda job, progress: seen.append((job.schema, job.kind)))
    new_job(db)
    assert Worker(reg, schema=db.schema, poll_interval=0).process_one() is True and seen == [(db.schema, "demo")]


def test_progress_is_stored_and_capped_below_100_until_completion(db):
    _, jid = new_job(db)
    seen = []

    def handler(job, progress):
        progress("half", 50); seen.append(row(db, jid)[:3])
        progress("too much", 150); seen.append(row(db, jid)[:3])

    reg = JobHandlerRegistry(); reg.register("demo", handler)
    Worker(reg, schema=db.schema, poll_interval=0).process_one()
    assert seen == [("processing", 50, "half"), ("processing", 99, "too much")] and row(db, jid)[:3] == ("completed", 100, "completed")


def test_a_failing_handler_marks_the_job_failed_with_its_error(db):
    _, jid = new_job(db)
    reg = JobHandlerRegistry(); reg.register("demo", lambda job, progress: (_ for _ in ()).throw(RuntimeError("boom")))
    Worker(reg, schema=db.schema, poll_interval=0).process_one()
    assert row(db, jid) == ("failed", 100, "failed", "boom")


def test_an_unknown_job_kind_fails_the_job_instead_of_hanging(db):
    _, jid = new_job(db, kind="nobody_handles_this")
    Worker(JobHandlerRegistry(), schema=db.schema, poll_interval=0).process_one()
    status, _, _, error = row(db, jid)
    assert status == "failed" and "no job handler registered for: nobody_handles_this" in error


def test_a_long_job_keeps_its_heartbeat_and_is_not_requeued(db):
    _, jid = new_job(db)

    def slow(job, progress):
        time.sleep(0.7)

    reg = JobHandlerRegistry(); reg.register("demo", slow)
    w = Worker(reg, schema=db.schema, poll_interval=0, heartbeat_interval=0.1, stale_after=1)
    t = threading.Thread(target=w.process_one); t.start()
    time.sleep(0.3)
    started, beat = row(db, jid, "started_at, heartbeat_at")
    db.cur.execute("UPDATE job SET started_at = now() - interval '1 hour' WHERE job_id = %s", (jid,))      # it began long ago, but it is alive
    time.sleep(0.25)
    assert w.recover_stale_jobs() == 0 and row(db, jid, "status")[0] == "processing"
    t.join()
    assert row(db, jid, "status")[0] == "completed"


def test_a_dead_job_without_recent_heartbeat_is_requeued_and_claimed_again(db):
    _, jid = new_job(db)
    db.cur.execute("UPDATE job SET status = 'processing', started_at = now() - interval '1 hour', heartbeat_at = now() - interval '30 minutes' WHERE job_id = %s", (jid,))
    seen = []
    reg = JobHandlerRegistry(); reg.register("demo", lambda job, progress: seen.append(job.job_id))
    w = Worker(reg, schema=db.schema, poll_interval=0, stale_after=60)
    assert w.recover_stale_jobs() == 1 and row(db, jid, "status, message")[:] == ("pending", "requeued after worker stop")
    assert w.process_one() is True and seen == [jid]


def test_two_workers_never_take_the_same_job(db):
    for _ in range(6):
        new_job(db)
    taken, lock = [], threading.Lock()

    def handler(job, progress):
        time.sleep(0.02)
        with lock:
            taken.append(job.job_id)

    reg = JobHandlerRegistry(); reg.register("demo", handler)

    def run():
        w = Worker(reg, schema=db.schema, poll_interval=0)
        while w.process_one():
            pass

    threads = [threading.Thread(target=run) for _ in range(3)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert len(taken) == 6 and len(set(taken)) == 6
