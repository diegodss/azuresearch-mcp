from __future__ import annotations

from core.search_provider import SearchProvider


class OpenSearchProvider(SearchProvider):
    def search(self, index: str, query: str, top: int = 5) -> list[dict]:
        raise NotImplementedError(
            "OpenSearchProvider is not configured yet. Set SEARCH_PROVIDER=azure for now."
        )

    def ingest(self, index: str, documents: list[dict]) -> None:
        raise NotImplementedError(
            "OpenSearchProvider is not configured yet. Set SEARCH_PROVIDER=azure for now."
        )
