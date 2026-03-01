from __future__ import annotations

from abc import ABC, abstractmethod


class SearchProvider(ABC):
    @abstractmethod
    def search(self, index: str, query: str, top: int = 5) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def ingest(self, index: str, documents: list[dict]) -> None:
        raise NotImplementedError
