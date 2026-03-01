from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.app_registry import AppRegistry
from core.search_provider import SearchProvider


@dataclass
class ToolSpec:
    name: str
    description: str
    handler: Callable[[str, int], str]


class ToolFactory:
    def __init__(self, provider: SearchProvider, config_path: str = "config/apps.yaml") -> None:
        self.provider = provider
        self.registry = AppRegistry(config_path=config_path)

    def build_tools(self) -> dict[str, ToolSpec]:
        tools: dict[str, ToolSpec] = {}
        for app in self.registry.apps:
            tool_name = f"search_kb_{app['id']}"
            tools[tool_name] = ToolSpec(
                name=tool_name,
                description=f"Search {app['name']} knowledge base",
                handler=self._build_handler(app["index"]),
            )
        return tools

    def _build_handler(self, index: str):
        def _handler(query: str, top: int = 5) -> str:
            rows = self.provider.search(index=index, query=query, top=top)
            if not rows:
                return "No results found."

            lines = []
            for i, row in enumerate(rows, start=1):
                title = row.get("title", "Untitled")
                score = row.get("score")
                content = (row.get("content") or "").strip().replace("\n", " ")
                snippet = content[:500]
                prefix = f"[{i}] {title}"
                if score is not None:
                    prefix += f" (score={score:.3f})" if isinstance(score, (int, float)) else f" (score={score})"
                lines.append(f"{prefix}\n{snippet}")
            return "\n\n".join(lines)

        return _handler
