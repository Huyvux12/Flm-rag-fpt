from __future__ import annotations

import time
from typing import Any

import httpx

from .config import Settings


class EmbeddingApiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.Client(base_url=settings.embedding_api_base_url.rstrip("/"), timeout=settings.request_timeout_s)

    def close(self) -> None:
        self.client.close()

    def health(self) -> dict[str, Any]:
        response = self.client.get("/")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"success": True, "data": payload}

    def info(self) -> dict[str, Any]:
        response = self.client.get("/openapi.json")
        response.raise_for_status()
        payload = response.json()
        return {
            "title": payload.get("info", {}).get("title"),
            "paths": list(payload.get("paths", {}).keys()),
        }

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._make_text_embeddings(query=texts[0], documents=texts)

    def embed_query(self, text: str) -> list[float]:
        embeddings = self._make_text_embeddings(query=text, documents=[text])
        if len(embeddings) != 1:
            raise ValueError("Expected a single query embedding")
        return embeddings[0]

    def _make_text_embeddings(self, query: str, documents: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        payload = {"query": query, "documents": documents}
        for retry_idx in range(self.settings.max_retries):
            try:
                response = self.client.post("/make_text_embedding", json=payload)
                response.raise_for_status()
                return self._parse_embedding_response(response.json())
            except Exception as exc:  # noqa: BLE001 - retry wrapper
                last_error = exc
                time.sleep(1.5 * (retry_idx + 1))
        raise RuntimeError(f"Embedding API request failed after retries: {last_error}")

    @staticmethod
    def _parse_embedding_response(payload: Any) -> list[list[float]]:
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            rows = payload["data"]
            if rows and isinstance(rows[0], list):
                return rows
        if isinstance(payload, list):
            if payload and isinstance(payload[0], (int, float)):
                return [payload]
            return payload
        raise ValueError(f"Unsupported embedding response payload: {payload}")
