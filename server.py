from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.auth import Authenticator
from core.provider_factory import build_search_provider
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


auth = Authenticator()
provider = build_search_provider()
tool_factory = ToolFactory(provider=provider, config_path="config/apps.yaml")
TOOLS: dict[str, ToolSpec] = tool_factory.build_tools()

app = FastAPI(title="azuresearch-mcp", version="1.0.0")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": os.getenv("SEARCH_PROVIDER", "azure"),
        "tools": sorted(TOOLS.keys()),
    }


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
                    "serverInfo": {"name": "azuresearch-mcp", "version": "1.0.0"},
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
                                    "top": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
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
