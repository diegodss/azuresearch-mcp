from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def test_mcp_tools_call_with_mock_provider(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_SEARCH_DATA_PATH", "config/mock_search_data.json")
    monkeypatch.setenv("AUTH_MODE", "token")
    monkeypatch.setenv("MCP_API_KEY", "dev-token")
    monkeypatch.setenv("QUEUE_BACKEND", "local")
    monkeypatch.setenv("JOB_DB_PATH", str(tmp_path / "jobs.db"))

    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")

    client = TestClient(server.app)

    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer dev-token"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_kb_technologyone",
                "arguments": {"query": "reset password", "top": 3},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    text = payload["result"]["content"][0]["text"]
    assert "Reset your TechnologyOne password" in text
