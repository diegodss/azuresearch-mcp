from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from core.job_store import JobStore

try:
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
except ImportError:  # pragma: no cover
    ServiceBusClient = None  # type: ignore[assignment]
    ServiceBusMessage = None  # type: ignore[assignment]


@dataclass
class QueueMessage:
    id: str
    payload: dict[str, Any]
    raw: Any


class QueueBackend:
    def enqueue(self, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def reserve(self, wait_seconds: int = 20) -> QueueMessage | None:
        raise NotImplementedError

    def ack(self, message: QueueMessage) -> None:
        raise NotImplementedError

    def nack(self, message: QueueMessage, delay_seconds: int = 30) -> None:
        raise NotImplementedError


class LocalSQLiteQueue(QueueBackend):
    def __init__(self, store: JobStore, lease_seconds: int = 300) -> None:
        self.store = store
        self.lease_seconds = lease_seconds

    def enqueue(self, payload: dict[str, Any]) -> None:
        now = int(time.time())
        with self.store._connect() as conn:  # noqa: SLF001
            conn.execute(
                """
                INSERT INTO ingestion_queue (payload_json, available_at, leased_until, attempts, created_at)
                VALUES (?, ?, NULL, 0, ?)
                """,
                (json.dumps(payload), now, now),
            )

    def reserve(self, wait_seconds: int = 20) -> QueueMessage | None:
        deadline = time.time() + max(1, wait_seconds)
        while time.time() < deadline:
            now = int(time.time())
            lease_until = now + self.lease_seconds
            with self.store._connect() as conn:  # noqa: SLF001
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT id, payload_json
                    FROM ingestion_queue
                    WHERE available_at <= ?
                      AND (leased_until IS NULL OR leased_until <= ?)
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (now, now),
                ).fetchone()

                if row is None:
                    conn.commit()
                else:
                    conn.execute(
                        """
                        UPDATE ingestion_queue
                        SET leased_until = ?, attempts = attempts + 1
                        WHERE id = ?
                        """,
                        (lease_until, row["id"]),
                    )
                    conn.commit()
                    payload = json.loads(row["payload_json"])
                    return QueueMessage(id=str(row["id"]), payload=payload, raw=row["id"])

            time.sleep(1)

        return None

    def ack(self, message: QueueMessage) -> None:
        with self.store._connect() as conn:  # noqa: SLF001
            conn.execute("DELETE FROM ingestion_queue WHERE id = ?", (int(message.id),))

    def nack(self, message: QueueMessage, delay_seconds: int = 30) -> None:
        next_available = int(time.time()) + max(1, delay_seconds)
        with self.store._connect() as conn:  # noqa: SLF001
            conn.execute(
                """
                UPDATE ingestion_queue
                SET leased_until = NULL, available_at = ?
                WHERE id = ?
                """,
                (next_available, int(message.id)),
            )


class AzureServiceBusQueue(QueueBackend):
    def __init__(self, connection_string: str, queue_name: str) -> None:
        if ServiceBusClient is None or ServiceBusMessage is None:  # pragma: no cover
            raise RuntimeError("azure-servicebus is not installed")
        self.queue_name = queue_name
        self.client = ServiceBusClient.from_connection_string(connection_string)
        self.sender = self.client.get_queue_sender(queue_name=queue_name)
        self.receiver = self.client.get_queue_receiver(queue_name=queue_name)

    def enqueue(self, payload: dict[str, Any]) -> None:
        self.sender.send_messages(ServiceBusMessage(json.dumps(payload)))

    def reserve(self, wait_seconds: int = 20) -> QueueMessage | None:
        messages = self.receiver.receive_messages(max_message_count=1, max_wait_time=wait_seconds)
        if not messages:
            return None
        message = messages[0]
        body = b"".join(message.body)
        payload = json.loads(body.decode("utf-8"))
        message_id = str(message.message_id or payload.get("job_id") or "unknown")
        return QueueMessage(id=message_id, payload=payload, raw=message)

    def ack(self, message: QueueMessage) -> None:
        self.receiver.complete_message(message.raw)

    def nack(self, message: QueueMessage, delay_seconds: int = 30) -> None:
        _ = delay_seconds
        self.receiver.abandon_message(message.raw)


def build_queue_backend(store: JobStore | None = None) -> QueueBackend:
    backend = os.getenv("QUEUE_BACKEND", "local").strip().lower()
    if backend == "local":
        return LocalSQLiteQueue(store=store or JobStore())

    if backend == "servicebus":
        conn_str = os.getenv("AZURE_SERVICEBUS_CONNECTION_STRING")
        queue_name = os.getenv("AZURE_SERVICEBUS_QUEUE_NAME", "ingestion-jobs")
        if not conn_str:
            raise ValueError("AZURE_SERVICEBUS_CONNECTION_STRING is required for servicebus backend")
        return AzureServiceBusQueue(connection_string=conn_str, queue_name=queue_name)

    raise ValueError("Unsupported QUEUE_BACKEND. Use 'local' or 'servicebus'.")
