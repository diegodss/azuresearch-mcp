from __future__ import annotations

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import msal
import requests

from ingestion.base_ingester import BaseIngester, chunk_text
from ingestion.pdf_ingester import PdfIngester
from ingestion.word_ingester import WordIngester

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


class SharePointIngester(BaseIngester):
    def _graph_token(self) -> str:
        tenant = os.getenv("SHAREPOINT_TENANT_ID")
        client_id = os.getenv("SHAREPOINT_CLIENT_ID")
        client_secret = os.getenv("SHAREPOINT_CLIENT_SECRET")
        if not tenant or not client_id or not client_secret:
            raise ValueError(
                "SHAREPOINT_TENANT_ID, SHAREPOINT_CLIENT_ID, and SHAREPOINT_CLIENT_SECRET are required"
            )

        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            authority=f"https://login.microsoftonline.com/{tenant}",
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        token = result.get("access_token")
        if not token:
            raise RuntimeError(f"Failed to acquire Graph token: {result}")
        return token

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def load_documents(self, args: argparse.Namespace) -> list[dict]:
        token = self._graph_token()
        site = self._resolve_site(token, args.site_url)
        drive = self._resolve_drive(token, site["id"], args.library)
        items = self._list_drive_items(token, site["id"], drive["id"])

        docs: list[dict] = []
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            for item in items:
                name = item.get("name", "")
                if "file" not in item:
                    continue

                ext = Path(name).suffix.lower()
                if ext not in {".txt", ".md", ".pdf", ".docx"}:
                    continue

                download_url = item.get("@microsoft.graph.downloadUrl")
                if not download_url:
                    continue
                content = requests.get(download_url, timeout=90)
                content.raise_for_status()

                local_file = tmpdir / name
                local_file.write_bytes(content.content)

                if ext in {".txt", ".md"}:
                    text = local_file.read_text(errors="ignore")
                    for idx, chunk in enumerate(chunk_text(text, chunk_size=args.chunk_size), start=1):
                        docs.append(
                            {
                                "id": f"{item['id']}-c{idx}",
                                "title": name,
                                "content": chunk,
                                "source": item.get("webUrl", args.site_url),
                            }
                        )
                elif ext == ".pdf":
                    pdf_docs = PdfIngester(app_id=self.app["id"]).load_documents(
                        argparse.Namespace(path=str(local_file), chunk_size=args.chunk_size)
                    )
                    docs.extend(pdf_docs)
                elif ext == ".docx":
                    word_docs = WordIngester(app_id=self.app["id"]).load_documents(
                        argparse.Namespace(path=str(local_file), chunk_size=args.chunk_size)
                    )
                    docs.extend(word_docs)

        return docs

    def _resolve_site(self, token: str, site_url: str) -> dict:
        hostname = site_url.split("/")[2]
        path = "/" + "/".join(site_url.split("/")[3:])
        url = f"{GRAPH_ROOT}/sites/{hostname}:{path}"
        response = requests.get(url, headers=self._headers(token), timeout=30)
        response.raise_for_status()
        return response.json()

    def _resolve_drive(self, token: str, site_id: str, library: str | None) -> dict:
        url = f"{GRAPH_ROOT}/sites/{site_id}/drives"
        response = requests.get(url, headers=self._headers(token), timeout=30)
        response.raise_for_status()
        drives = response.json().get("value", [])
        if not drives:
            raise RuntimeError("No drives found for SharePoint site")
        if not library:
            return drives[0]
        for drive in drives:
            if drive.get("name", "").lower() == library.lower():
                return drive
        raise RuntimeError(f"Drive '{library}' not found")

    def _list_drive_items(self, token: str, site_id: str, drive_id: str) -> list[dict]:
        queue = ["root"]
        output: list[dict] = []
        while queue:
            item = queue.pop(0)
            url = f"{GRAPH_ROOT}/sites/{site_id}/drives/{drive_id}/items/{item}/children"
            response = requests.get(url, headers=self._headers(token), timeout=30)
            response.raise_for_status()
            rows = response.json().get("value", [])
            for row in rows:
                output.append(row)
                if "folder" in row:
                    queue.append(row["id"])
        return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest from SharePoint library")
    parser.add_argument("--app", required=True, help="App id from config/apps.yaml")
    parser.add_argument("--site-url", required=True, help="SharePoint site URL")
    parser.add_argument("--library", required=False, help="Optional library name")
    parser.add_argument("--chunk-size", type=int, default=1200)
    args = parser.parse_args()

    ingester = SharePointIngester(app_id=args.app)
    count = ingester.ingest(args)
    print(f"Ingested {count} chunks into index {ingester.index}")


if __name__ == "__main__":
    main()
