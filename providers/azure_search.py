from __future__ import annotations

import os
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from core.search_provider import SearchProvider


class AzureSearchProvider(SearchProvider):
    def __init__(self, endpoint: str | None = None, key: str | None = None) -> None:
        self.endpoint = endpoint or os.getenv("AZURE_SEARCH_ENDPOINT")
        self.key = key or os.getenv("AZURE_SEARCH_KEY")
        if not self.endpoint or not self.key:
            raise ValueError("AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY are required")

    def _client(self, index: str) -> SearchClient:
        return SearchClient(
            endpoint=self.endpoint,
            index_name=index,
            credential=AzureKeyCredential(self.key),
        )

    def search(self, index: str, query: str, top: int = 5) -> list[dict]:
        client = self._client(index)
        results = client.search(search_text=query, top=top)
        return [self._normalize_result(item) for item in results]

    def ingest(self, index: str, documents: list[dict]) -> None:
        if not documents:
            return
        client = self._client(index)
        payload = []
        for i, doc in enumerate(documents):
            normalized = dict(doc)
            normalized.setdefault("id", str(i))
            payload.append(normalized)
        client.upload_documents(documents=payload)

    @staticmethod
    def _normalize_result(item: dict[str, Any]) -> dict:
        if not isinstance(item, dict):
            item = dict(item)
        score = item.pop("@search.score", None)
        return {
            "score": score,
            "title": item.get("title") or item.get("source") or "Untitled",
            "content": item.get("content") or item.get("text") or "",
            "metadata": {k: v for k, v in item.items() if k not in {"title", "content", "text"}},
        }
