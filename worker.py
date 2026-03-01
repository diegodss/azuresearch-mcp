from __future__ import annotations

import os
import signal
import time

from dotenv import load_dotenv

from core.job_store import JobStore
from core.queue_backend import QueueMessage, build_queue_backend
from ingestion.runner import run_ingestion_job

load_dotenv()

RUNNING = True


def _stop_handler(signum: int, frame) -> None:  # noqa: ANN001
    _ = signum, frame
    global RUNNING
    RUNNING = False


def process_message(store: JobStore, message: QueueMessage) -> None:
    payload = message.payload
    job_id = payload.get("job_id")
    if not job_id:
        raise ValueError("Queue payload missing job_id")

    job = store.get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    if job["status"] in {"cancelled", "succeeded"}:
        return

    store.mark_running(job_id)

    count = run_ingestion_job(
        app_id=job["app_id"],
        ingester_type=job["ingester_type"],
        source=job["source"],
        options=job["options"],
    )
    store.mark_succeeded(job_id, processed_chunks=count)


def main() -> None:
    signal.signal(signal.SIGINT, _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    wait_seconds = int(os.getenv("WORKER_POLL_SECONDS", "20"))
    retry_delay = int(os.getenv("WORKER_RETRY_DELAY_SECONDS", "30"))

    store = JobStore()
    queue = build_queue_backend(store=store)

    print("Worker started")
    while RUNNING:
        msg = queue.reserve(wait_seconds=wait_seconds)
        if not msg:
            continue

        try:
            process_message(store=store, message=msg)
            queue.ack(msg)
        except Exception as exc:  # noqa: BLE001
            job_id = msg.payload.get("job_id")
            if job_id:
                store.mark_failed(job_id, error=str(exc))
                queue.nack(msg, delay_seconds=retry_delay)
            else:
                queue.ack(msg)
            time.sleep(1)

    print("Worker stopped")


if __name__ == "__main__":
    main()
