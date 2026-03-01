from __future__ import annotations

from pathlib import Path

from core.tool_factory import ToolFactory


class FakeProvider:
    def search(self, index: str, query: str, top: int = 5) -> list[dict]:
        assert index == "kb-technologyone"
        assert query == "how do I reset password?"
        assert top == 3
        return [
            {"title": "Reset Password", "content": "Use self service reset", "score": 1.0},
        ]

    def ingest(self, index: str, documents: list[dict]) -> None:
        return None


def test_tool_factory_generates_tools(tmp_path: Path) -> None:
    config = tmp_path / "apps.yaml"
    config.write_text(
        """
apps:
  - id: technologyone
    name: TechnologyOne
    description: ERP system knowledge base
    index: kb-technologyone
""".strip()
    )

    tools = ToolFactory(provider=FakeProvider(), config_path=str(config)).build_tools()
    assert "search_kb_technologyone" in tools

    out = tools["search_kb_technologyone"].handler("how do I reset password?", 3)
    assert "Reset Password" in out
    assert "self service reset" in out
