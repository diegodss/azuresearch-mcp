from __future__ import annotations

import os
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from core.auth import Authenticator
from core.job_store import JobStore
from core.provider_factory import build_search_provider
from core.queue_backend import build_queue_backend
from core.tool_factory import ToolFactory, ToolSpec

load_dotenv()


class JsonRpcRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    id: int | str | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class CreateIngestionJobRequest(BaseModel):
    app_id: str
    ingester_type: Literal["pdf", "word", "sharepoint", "video"]
    source: str = Field(description="Local path (pdf/word/video) or SharePoint site URL")
    options: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class IngestionJobResponse(BaseModel):
    job: dict[str, Any]


auth = Authenticator()
provider = build_search_provider()
tool_factory = ToolFactory(provider=provider, config_path="config/apps.yaml")
TOOLS: dict[str, ToolSpec] = tool_factory.build_tools()
job_store = JobStore()
queue_backend = build_queue_backend(store=job_store)

app = FastAPI(title="azuresearch-mcp", version="1.1.0")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": os.getenv("SEARCH_PROVIDER", "azure"),
        "queue_backend": os.getenv("QUEUE_BACKEND", "local"),
        "tools": sorted(TOOLS.keys()),
    }


@app.post("/ingestion/jobs", response_model=IngestionJobResponse)
def create_ingestion_job(
    body: CreateIngestionJobRequest,
    _user: dict[str, Any] = Depends(auth.dependency()),
) -> IngestionJobResponse:
    try:
        tool_factory.registry.get_by_id(body.app_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    options = dict(body.options or {})
    options.setdefault("chunk_size", 1200)

    if body.idempotency_key:
        existing = job_store.get_by_idempotency_key(body.idempotency_key)
        if existing:
            return IngestionJobResponse(job=existing)

    job = job_store.create_job(
        app_id=body.app_id,
        ingester_type=body.ingester_type,
        source=body.source,
        options=options,
        idempotency_key=body.idempotency_key,
    )
    if job["status"] == "queued":
        queue_backend.enqueue({"job_id": job["id"]})
    return IngestionJobResponse(job=job)


@app.get("/ingestion/jobs/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(
    job_id: str,
    _user: dict[str, Any] = Depends(auth.dependency()),
) -> IngestionJobResponse:
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Unknown job '{job_id}'")
    return IngestionJobResponse(job=job)


@app.get("/ingestion/jobs")
def list_ingestion_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _user: dict[str, Any] = Depends(auth.dependency()),
) -> dict[str, Any]:
    return {"jobs": job_store.list_jobs(status=status, limit=limit)}


@app.post("/ingestion/jobs/{job_id}/cancel")
def cancel_ingestion_job(
    job_id: str,
    _user: dict[str, Any] = Depends(auth.dependency()),
) -> dict[str, Any]:
    cancelled = job_store.cancel(job_id)
    if not cancelled:
        raise HTTPException(status_code=409, detail="Job cannot be cancelled in current state")
    job = job_store.get_job(job_id)
    return {"job": job}


@app.post("/mcp", response_model=JsonRpcResponse)
def mcp_endpoint(
    body: JsonRpcRequest,
    _user: dict[str, Any] = Depends(auth.dependency()),
) -> JsonRpcResponse:
    try:
        if body.method == "initialize":
            return JsonRpcResponse(
                id=body.id,
                result={
                    "protocolVersion": "2025-03-26",
                    "serverInfo": {"name": "azuresearch-mcp", "version": "1.1.0"},
                    "capabilities": {"tools": {}},
                },
            )

        if body.method == "tools/list":
            return JsonRpcResponse(
                id=body.id,
                result={
                    "tools": [
                        {
                            "name": spec.name,
                            "description": spec.description,
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string"},
                                    "top": {
                                        "type": "integer",
                                        "default": 5,
                                        "minimum": 1,
                                        "maximum": 50,
                                    },
                                },
                                "required": ["query"],
                            },
                        }
                        for spec in TOOLS.values()
                    ]
                },
            )

        if body.method == "tools/call":
            tool_name = body.params.get("name")
            args = body.params.get("arguments") or {}
            if tool_name not in TOOLS:
                raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_name}'")
            query = args.get("query")
            top = int(args.get("top", 5))
            if not query:
                raise HTTPException(status_code=400, detail="'query' is required")
            output = TOOLS[tool_name].handler(query=query, top=top)
            return JsonRpcResponse(
                id=body.id,
                result={
                    "content": [{"type": "text", "text": output}],
                    "isError": False,
                },
            )

        raise HTTPException(status_code=404, detail=f"Unsupported method '{body.method}'")

    except HTTPException as exc:
        return JsonRpcResponse(
            id=body.id,
            error={"code": exc.status_code, "message": exc.detail},
        )
    except Exception as exc:  # noqa: BLE001
        return JsonRpcResponse(
            id=body.id,
            error={"code": 500, "message": str(exc)},
        )
