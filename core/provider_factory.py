from __future__ import annotations

import os

from core.search_provider import SearchProvider
from providers.azure_search import AzureSearchProvider
from providers.opensearch import OpenSearchProvider


def build_search_provider() -> SearchProvider:
    provider = os.getenv("SEARCH_PROVIDER", "azure").strip().lower()

    if provider == "azure":
        return AzureSearchProvider()
    if provider == "opensearch":
        return OpenSearchProvider()

    raise ValueError(
        f"Unsupported SEARCH_PROVIDER '{provider}'. Supported: azure, opensearch"
    )
