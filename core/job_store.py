from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JobStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv("JOB_DB_PATH", "data/jobs.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id TEXT PRIMARY KEY,
                    app_id TEXT NOT NULL,
                    ingester_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    processed_chunks INTEGER,
                    error TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    idempotency_key TEXT UNIQUE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload_json TEXT NOT NULL,
                    available_at INTEGER NOT NULL,
                    leased_until INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ingestion_queue_available ON ingestion_queue (available_at, leased_until)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON ingestion_jobs (status, created_at DESC)"
            )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    def create_job(
        self,
        app_id: str,
        ingester_type: str,
        source: str,
        options: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing:
                return existing

        job_id = str(uuid.uuid4())
        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_jobs (
                    id, app_id, ingester_type, source, options_json, status, created_at,
                    updated_at, processed_chunks, retry_count, idempotency_key
                )
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, NULL, 0, ?)
                """,
                (
                    job_id,
                    app_id,
                    ingester_type,
                    source,
                    json.dumps(options),
                    now,
                    now,
                    idempotency_key,
                ),
            )
        return self.get_job(job_id)

    def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM ingestion_jobs"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_job(row) for row in rows]

    def mark_running(self, job_id: str) -> None:
        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (now, now, job_id),
            )

    def mark_succeeded(self, job_id: str, processed_chunks: int) -> None:
        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'succeeded', processed_chunks = ?, finished_at = ?, updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (processed_chunks, now, now, job_id),
            )

    def mark_failed(self, job_id: str, error: str) -> None:
        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'failed', error = ?, retry_count = retry_count + 1, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (error[:4000], now, now, job_id),
            )

    def cancel(self, job_id: str) -> bool:
        now = self._now_iso()
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'cancelled', finished_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (now, now, job_id),
            )
        return result.rowcount > 0

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "app_id": row["app_id"],
            "ingester_type": row["ingester_type"],
            "source": row["source"],
            "options": json.loads(row["options_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "processed_chunks": row["processed_chunks"],
            "error": row["error"],
            "retry_count": row["retry_count"],
            "idempotency_key": row["idempotency_key"],
        }
