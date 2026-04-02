from __future__ import annotations

import hashlib
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

from .config import Settings


class QdrantStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.qdrant_local_path:
            self.client = QdrantClient(path=settings.qdrant_local_path)
            self.is_local = True
        else:
            self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
            self.is_local = False

    def ensure_collection(self, collection_name: str) -> None:
        existing = {collection.name for collection in self.client.get_collections().collections}
        if collection_name not in existing:
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=self.settings.vector_size, distance=models.Distance.COSINE),
            )
        if self.is_local:
            return
        for field_name, schema in {
            "chunk_id": models.PayloadSchemaType.KEYWORD,
            "course_id": models.PayloadSchemaType.KEYWORD,
            "major_code": models.PayloadSchemaType.KEYWORD,
            "semester": models.PayloadSchemaType.INTEGER,
            "combo_short_name": models.PayloadSchemaType.KEYWORD,
            "chunk_type": models.PayloadSchemaType.KEYWORD,
            "syllabus_id": models.PayloadSchemaType.KEYWORD,
            "canonical_syllabus_key": models.PayloadSchemaType.KEYWORD,
            "parent_offering_key": models.PayloadSchemaType.KEYWORD,
        }.items():
            try:
                self.client.create_payload_index(collection_name, field_name, schema)
            except Exception:
                pass

    def upload_records(self, collection_name: str, records: list[dict[str, Any]], vectors: list[list[float]]) -> None:
        ids = []
        payloads = []
        for record in records:
            payload = dict(record["payload"])
            payload.setdefault("chunk_id", record["id"])
            ids.append(self._point_id(record["id"]))
            payloads.append(payload)
        self.client.upload_collection(
            collection_name=collection_name,
            ids=ids,
            vectors=vectors,
            payload=payloads,
        )

    def search(self, collection_name: str, query_vector: list[float], top_k: int, metadata_filter: dict[str, Any] | None = None) -> list[tuple[dict[str, Any], float]]:
        q_filter = None
        if metadata_filter:
            conditions = []
            for key, value in metadata_filter.items():
                if isinstance(value, int):
                    conditions.append(models.FieldCondition(key=key, range=models.Range(gte=value, lte=value)))
                else:
                    conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
            q_filter = models.Filter(must=conditions)
        response = self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=q_filter,
            with_payload=True,
        )
        points = response.points if hasattr(response, "points") else response
        return [({"chunk_id": (point.payload or {}).get("chunk_id"), "payload": dict(point.payload or {}), "text": (point.payload or {}).get("text", "")}, float(point.score)) for point in points]

    @staticmethod
    def _point_id(chunk_id: str) -> int:
        return int(hashlib.sha1(chunk_id.encode("utf-8")).hexdigest()[:15], 16)
