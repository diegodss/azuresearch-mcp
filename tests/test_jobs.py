from __future__ import annotations

from pathlib import Path

from core.job_store import JobStore
from core.queue_backend import LocalSQLiteQueue


def test_job_store_lifecycle(tmp_path: Path) -> None:
    store = JobStore(db_path=str(tmp_path / "jobs.db"))
    job = store.create_job(
        app_id="technologyone",
        ingester_type="pdf",
        source="/tmp/docs",
        options={"chunk_size": 1000},
        idempotency_key="abc123",
    )

    assert job["status"] == "queued"
    assert job["app_id"] == "technologyone"

    same = store.create_job(
        app_id="technologyone",
        ingester_type="pdf",
        source="/tmp/docs",
        options={"chunk_size": 1000},
        idempotency_key="abc123",
    )
    assert same["id"] == job["id"]

    store.mark_running(job["id"])
    running = store.get_job(job["id"])
    assert running and running["status"] == "running"

    store.mark_succeeded(job["id"], processed_chunks=42)
    done = store.get_job(job["id"])
    assert done and done["status"] == "succeeded"
    assert done["processed_chunks"] == 42


def test_local_queue_roundtrip(tmp_path: Path) -> None:
    store = JobStore(db_path=str(tmp_path / "queue.db"))
    queue = LocalSQLiteQueue(store=store, lease_seconds=10)

    queue.enqueue({"job_id": "job-1"})
    message = queue.reserve(wait_seconds=2)
    assert message is not None
    assert message.payload["job_id"] == "job-1"

    queue.ack(message)
    missing = queue.reserve(wait_seconds=1)
    assert missing is None
