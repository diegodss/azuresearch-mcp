from __future__ import annotations

import argparse
from pathlib import Path

import fitz

from ingestion.base_ingester import BaseIngester, chunk_text


class PdfIngester(BaseIngester):
    def load_documents(self, args: argparse.Namespace) -> list[dict]:
        base = Path(args.path)
        files = [base] if base.is_file() else sorted(base.rglob("*.pdf"))
        docs: list[dict] = []

        for file_path in files:
            with fitz.open(file_path) as pdf:
                for page_idx, page in enumerate(pdf, start=1):
                    page_text = page.get_text("text")
                    for chunk_idx, chunk in enumerate(
                        chunk_text(page_text, chunk_size=args.chunk_size), start=1
                    ):
                        docs.append(
                            {
                                "id": f"{file_path.stem}-p{page_idx}-c{chunk_idx}",
                                "title": file_path.name,
                                "content": chunk,
                                "source": str(file_path),
                                "page": page_idx,
                            }
                        )
        return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest PDFs into app knowledge base")
    parser.add_argument("--app", required=True, help="App id from config/apps.yaml")
    parser.add_argument("--path", required=True, help="PDF file or directory")
    parser.add_argument("--chunk-size", type=int, default=1200)
    args = parser.parse_args()

    ingester = PdfIngester(app_id=args.app)
    count = ingester.ingest(args)
    print(f"Ingested {count} chunks into index {ingester.index}")


if __name__ == "__main__":
    main()
