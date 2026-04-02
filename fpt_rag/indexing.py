from __future__ import annotations

from pathlib import Path
from typing import Any

from .bm25_index import Bm25Index
from .config import Settings
from .dataset import batched, load_dataset_bundle
from .embedding_api import EmbeddingApiClient
from .qdrant_store import QdrantStore


def build_index_records(rows: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        chunk_id = row["chunk_id"]
        payload = dict(row)
        payload["embedding_model_version"] = settings.embedding_model_version
        records.append({"id": chunk_id, "text": row["text"], "payload": payload})
    return records


def _embed_in_batches(records: list[dict[str, Any]], embedding: EmbeddingApiClient, batch_size: int, label: str) -> list[list[float]]:
    vectors: list[list[float]] = []
    total = len(records)
    for idx, batch in enumerate(batched(records, batch_size), start=1):
        print(f"[{label}] embedding batch {idx} size={len(batch)}")
        vectors.extend(embedding.embed_documents([item["text"] for item in batch]))
    print(f"[{label}] embedded {total} records")
    return vectors


def _upload_in_batches(records: list[dict[str, Any]], vectors: list[list[float]], qdrant: QdrantStore, collection_name: str, batch_size: int, label: str) -> None:
    total = len(records)
    for idx, start in enumerate(range(0, total, batch_size), start=1):
        rec_batch = records[start:start + batch_size]
        vec_batch = vectors[start:start + batch_size]
        print(f"[{label}] upload batch {idx} size={len(rec_batch)}")
        qdrant.upload_records(collection_name, rec_batch, vec_batch)
    print(f"[{label}] uploaded {total} records to {collection_name}")


def build_indexes(settings: Settings, dataset_dir: str | None = None) -> dict[str, Any]:
    if dataset_dir:
        settings.dataset_dir = Path(dataset_dir).resolve()
        settings.offering_map_path = settings.dataset_dir / "offering_map.jsonl"
    print(f"Loading dataset from {settings.dataset_dir}")
    bundle = load_dataset_bundle(settings.dataset_dir)
    embedding = EmbeddingApiClient(settings)
    qdrant = QdrantStore(settings)

    curriculum_records = build_index_records(bundle["curriculum"], settings=settings)
    syllabus_records = build_index_records(bundle["syllabus_detail"], settings=settings)
    print(f"Prepared curriculum records={len(curriculum_records)} syllabus_records={len(syllabus_records)}")

    qdrant.ensure_collection(settings.qdrant_curriculum_collection)
    qdrant.ensure_collection(settings.qdrant_syllabus_collection)
    print("Collections ensured")

    curriculum_vectors = _embed_in_batches(curriculum_records, embedding, batch_size=settings.batch_size, label="curriculum")
    syllabus_vectors = _embed_in_batches(syllabus_records, embedding, batch_size=settings.batch_size, label="syllabus")

    _upload_in_batches(curriculum_records, curriculum_vectors, qdrant, settings.qdrant_curriculum_collection, batch_size=settings.batch_size, label="curriculum")
    _upload_in_batches(syllabus_records, syllabus_vectors, qdrant, settings.qdrant_syllabus_collection, batch_size=settings.batch_size, label="syllabus")

    print("Building BM25 artifacts")
    Bm25Index.build(curriculum_records).save(settings.bm25_curriculum_path)
    Bm25Index.build(syllabus_records).save(settings.bm25_syllabus_path)

    embedding.close()
    return {
        "dataset_dir": str(settings.dataset_dir),
        "curriculum_indexed": len(curriculum_records),
        "syllabus_indexed": len(syllabus_records),
        "bm25_curriculum": str(settings.bm25_curriculum_path),
        "bm25_syllabus": str(settings.bm25_syllabus_path),
        "qdrant_mode": "local" if settings.qdrant_local_path else "server",
        "qdrant_target": settings.qdrant_local_path or settings.qdrant_url,
        "collections": [settings.qdrant_curriculum_collection, settings.qdrant_syllabus_collection],
    }
