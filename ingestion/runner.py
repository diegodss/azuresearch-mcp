from __future__ import annotations

import argparse
from typing import Any

from ingestion.pdf_ingester import PdfIngester
from ingestion.sharepoint_ingester import SharePointIngester
from ingestion.video_ingester import VideoIngester
from ingestion.word_ingester import WordIngester

INGESTER_TYPES = {
    "pdf": PdfIngester,
    "word": WordIngester,
    "sharepoint": SharePointIngester,
    "video": VideoIngester,
}


def run_ingestion_job(
    app_id: str,
    ingester_type: str,
    source: str,
    options: dict[str, Any] | None = None,
) -> int:
    options = options or {}
    ingester_type = ingester_type.strip().lower()
    if ingester_type not in INGESTER_TYPES:
        raise ValueError(f"Unsupported ingester_type '{ingester_type}'")

    chunk_size = int(options.get("chunk_size", 1200))
    ingester_cls = INGESTER_TYPES[ingester_type]
    ingester = ingester_cls(app_id=app_id)

    if ingester_type in {"pdf", "word", "video"}:
        args = argparse.Namespace(path=source, chunk_size=chunk_size)
    elif ingester_type == "sharepoint":
        args = argparse.Namespace(
            site_url=source,
            library=options.get("library"),
            chunk_size=chunk_size,
        )
    else:  # pragma: no cover
        raise ValueError(f"Unsupported ingester_type '{ingester_type}'")

    return ingester.ingest(args)
