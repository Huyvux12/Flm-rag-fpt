from __future__ import annotations

import math
import time
from typing import Any

import httpx

from .config import Settings


class EmbeddingApiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = (
            httpx.Client(base_url=settings.embedding_api_base_url.rstrip("/"), timeout=settings.request_timeout_s)
            if settings.embedding_provider == "api" else None
        )
        self.model = None
        if settings.embedding_provider == "sentence-transformers":
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("Install local embeddings with: uv sync --extra embedding-local") from exc
            self.model = SentenceTransformer(settings.embedding_local_model)

    def close(self) -> None:
        if self.client is not None:
            self.client.close()

    def health(self) -> dict[str, Any]:
        if self.client is None:
            return {"provider": "sentence-transformers", "model": self.settings.embedding_local_model}
        response = self.client.get("/")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"success": True, "data": payload}

    def info(self) -> dict[str, Any]:
        if self.client is None:
            return {"title": "sentence-transformers", "paths": []}
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
        if self.model is not None:
            vectors = self.model.encode_document(texts, normalize_embeddings=True)
            return self._validate_vectors(vectors.tolist(), expected_count=len(texts))
        return self._make_text_embeddings(query=texts[0], documents=texts)

    def embed_query(self, text: str) -> list[float]:
        if self.model is not None:
            vectors = self.model.encode_query([text], normalize_embeddings=True)
            embeddings = self._validate_vectors(vectors.tolist(), expected_count=1)
        else:
            embeddings = self._make_text_embeddings(query=text, documents=[text])
        if len(embeddings) != 1:
            raise ValueError("Expected a single query embedding")
        return embeddings[0]

    def _make_text_embeddings(self, query: str, documents: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        payload = {"query": query, "documents": documents}
        for retry_idx in range(self.settings.max_retries):
            try:
                if self.client is None:
                    raise RuntimeError("API client is disabled")
                response = self.client.post("/make_text_embedding", json=payload)
                response.raise_for_status()
                return self._validate_vectors(self._parse_embedding_response(response.json()), len(documents))
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                last_error = exc
                if retry_idx + 1 < self.settings.max_retries:
                    time.sleep(1.5 * (retry_idx + 1))
        raise RuntimeError(f"Embedding API request failed after retries: {last_error}")

    def _validate_vectors(self, vectors: list[list[float]], expected_count: int) -> list[list[float]]:
        if len(vectors) != expected_count:
            raise ValueError(f"Expected {expected_count} embeddings, got {len(vectors)}")
        for idx, vector in enumerate(vectors):
            if len(vector) != self.settings.vector_size or not all(
                isinstance(value, (int, float)) and math.isfinite(value) for value in vector
            ):
                raise ValueError(f"Invalid embedding dimensions or values at index {idx}")
        return vectors

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
