from __future__ import annotations

from providers.mock_search import MockSearchProvider


def test_mock_provider_returns_hits() -> None:
    provider = MockSearchProvider(data_path="config/mock_search_data.json")
    rows = provider.search(index="kb-technologyone", query="reset password", top=3)

    assert rows
    assert "Reset" in rows[0]["title"]
