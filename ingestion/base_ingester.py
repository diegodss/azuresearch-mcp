from __future__ import annotations

import argparse
from abc import ABC, abstractmethod

from core.app_registry import AppRegistry
from core.provider_factory import build_search_provider


class BaseIngester(ABC):
    def __init__(self, app_id: str, config_path: str = "config/apps.yaml") -> None:
        self.registry = AppRegistry(config_path=config_path)
        app = self.registry.get_by_id(app_id)
        self.app = app
        self.index = app["index"]
        self.provider = build_search_provider()

    @abstractmethod
    def load_documents(self, args: argparse.Namespace) -> list[dict]:
        raise NotImplementedError

    def ingest(self, args: argparse.Namespace) -> int:
        documents = self.load_documents(args)
        self.provider.ingest(index=self.index, documents=documents)
        return len(documents)


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    text = " ".join((text or "").split())
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks
