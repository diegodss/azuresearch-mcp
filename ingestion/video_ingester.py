from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests

from ingestion.base_ingester import BaseIngester, chunk_text


class VideoIngester(BaseIngester):
    def load_documents(self, args: argparse.Namespace) -> list[dict]:
        base = Path(args.path)
        files = [base] if base.is_file() else [p for p in base.rglob("*") if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".wav", ".mp3"}]
        docs: list[dict] = []

        for file_path in files:
            transcript = self._transcribe(file_path)
            for idx, chunk in enumerate(chunk_text(transcript, chunk_size=args.chunk_size), start=1):
                docs.append(
                    {
                        "id": f"{file_path.stem}-c{idx}",
                        "title": file_path.name,
                        "content": chunk,
                        "source": str(file_path),
                    }
                )

        return docs

    def _transcribe(self, file_path: Path) -> str:
        if os.getenv("AZURE_VIDEO_INDEXER_KEY"):
            return self._transcribe_with_video_indexer(file_path)
        return self._transcribe_with_local_whisper(file_path)

    @staticmethod
    def _transcribe_with_local_whisper(file_path: Path) -> str:
        try:
            import whisper  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Install openai-whisper or configure AZURE_VIDEO_INDEXER_KEY for video ingestion"
            ) from exc

        model_name = os.getenv("WHISPER_MODEL", "base")
        model = whisper.load_model(model_name)
        result = model.transcribe(str(file_path))
        return result.get("text", "")

    @staticmethod
    def _transcribe_with_video_indexer(file_path: Path) -> str:
        key = os.getenv("AZURE_VIDEO_INDEXER_KEY")
        account_id = os.getenv("AZURE_VIDEO_INDEXER_ACCOUNT_ID")
        location = os.getenv("AZURE_VIDEO_INDEXER_LOCATION", "trial")
        if not key or not account_id:
            raise RuntimeError("AZURE_VIDEO_INDEXER_KEY and AZURE_VIDEO_INDEXER_ACCOUNT_ID are required")

        auth = requests.get(
            f"https://api.videoindexer.ai/Auth/{location}/Accounts/{account_id}/AccessToken",
            params={"allowEdit": "true"},
            headers={"Ocp-Apim-Subscription-Key": key},
            timeout=60,
        )
        auth.raise_for_status()
        token = auth.text.strip('"')

        with file_path.open("rb") as f:
            upload = requests.post(
                f"https://api.videoindexer.ai/{location}/Accounts/{account_id}/Videos",
                params={"name": file_path.stem, "accessToken": token},
                files={"file": (file_path.name, f)},
                timeout=180,
            )
        upload.raise_for_status()
        video_id = upload.json()["id"]

        for _ in range(60):
            state_resp = requests.get(
                f"https://api.videoindexer.ai/{location}/Accounts/{account_id}/Videos/{video_id}/Index",
                params={"accessToken": token},
                timeout=30,
            )
            state_resp.raise_for_status()
            payload = state_resp.json()
            if payload.get("state") == "Processed":
                insights = payload.get("videos", [{}])[0].get("insights", {})
                transcript = []
                for item in insights.get("transcript", []):
                    transcript.append(item.get("text", ""))
                return "\n".join(transcript)

        raise TimeoutError("Video Indexer processing did not complete in time")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest video/audio transcripts")
    parser.add_argument("--app", required=True, help="App id from config/apps.yaml")
    parser.add_argument("--path", required=True, help="Video file or directory")
    parser.add_argument("--chunk-size", type=int, default=1200)
    args = parser.parse_args()

    ingester = VideoIngester(app_id=args.app)
    count = ingester.ingest(args)
    print(json.dumps({"index": ingester.index, "chunks": count}, indent=2))


if __name__ == "__main__":
    main()
