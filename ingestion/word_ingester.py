from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document

from ingestion.base_ingester import BaseIngester, chunk_text


class WordIngester(BaseIngester):
    def load_documents(self, args: argparse.Namespace) -> list[dict]:
        base = Path(args.path)
        files = [base] if base.is_file() else sorted(base.rglob("*.docx"))
        docs: list[dict] = []

        for file_path in files:
            doc = Document(file_path)
            section_title = "Introduction"
            buffer: list[str] = []
            section_id = 0

            def flush_section() -> None:
                nonlocal section_id
                text = "\n".join(buffer).strip()
                if not text:
                    return
                section_id += 1
                for chunk_idx, chunk in enumerate(
                    chunk_text(text, chunk_size=args.chunk_size), start=1
                ):
                    docs.append(
                        {
                            "id": f"{file_path.stem}-s{section_id}-c{chunk_idx}",
                            "title": f"{file_path.name}: {section_title}",
                            "content": chunk,
                            "source": str(file_path),
                            "section": section_title,
                        }
                    )

            for para in doc.paragraphs:
                style_name = (para.style.name or "").lower()
                text = para.text.strip()
                if not text:
                    continue

                if "heading" in style_name:
                    flush_section()
                    buffer = []
                    section_title = text
                else:
                    buffer.append(text)

            flush_section()

        return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Word docs into app knowledge base")
    parser.add_argument("--app", required=True, help="App id from config/apps.yaml")
    parser.add_argument("--path", required=True, help="DOCX file or directory")
    parser.add_argument("--chunk-size", type=int, default=1200)
    args = parser.parse_args()

    ingester = WordIngester(app_id=args.app)
    count = ingester.ingest(args)
    print(f"Ingested {count} chunks into index {ingester.index}")


if __name__ == "__main__":
    main()
