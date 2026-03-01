from __future__ import annotations

import json
import os
import re
from pathlib import Path

from core.search_provider import SearchProvider


class MockSearchProvider(SearchProvider):
    def __init__(self, data_path: str | None = None) -> None:
        self.data_path = data_path or os.getenv(
            "MOCK_SEARCH_DATA_PATH", "config/mock_search_data.json"
        )
        self._indexes = self._load()

    def _load(self) -> dict[str, list[dict]]:
        path = Path(self.data_path)
        if not path.exists():
            raise ValueError(f"Mock data file not found: {path}")
        payload = json.loads(path.read_text())
        indexes = payload.get("indexes", {})
        if not isinstance(indexes, dict):
            raise ValueError("Mock data must include an 'indexes' object")
        return indexes

    def search(self, index: str, query: str, top: int = 5) -> list[dict]:
        docs = self._indexes.get(index, [])
        query_terms = self._tokenize(query)
        scored: list[dict] = []

        for doc in docs:
            content = str(doc.get("content", ""))
            title = str(doc.get("title", ""))
            haystack = f"{title} {content}".lower()
            score = float(sum(1 for t in query_terms if t in haystack))
            if score <= 0:
                continue
            scored.append(
                {
                    "title": title or "Untitled",
                    "content": content,
                    "score": score,
                    "metadata": doc.get("metadata", {}),
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top]

    def ingest(self, index: str, documents: list[dict]) -> None:
        existing = self._indexes.setdefault(index, [])
        existing.extend(documents)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [t for t in re.split(r"\W+", text.lower()) if t]
