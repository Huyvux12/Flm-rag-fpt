from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    workspace_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    dataset_dir: Path = field(init=False)
    artifacts_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1] / "artifacts")
    embedding_api_base_url: str = field(default_factory=lambda: os.getenv("EMBEDDING_API_BASE_URL", "https://wildojisan-embeddinggemma-300m-fastapi.hf.space"))
    embedding_model_version: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL_VERSION", "embeddinggemma-300m-onnx-v1"))
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333"))
    qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY"))
    qdrant_local_path: str | None = field(default_factory=lambda: os.getenv("QDRANT_LOCAL_PATH") or None)
    qdrant_syllabus_collection: str = field(default_factory=lambda: os.getenv("QDRANT_SYLLABUS_COLLECTION", "fpt_syllabus_detail_v1"))
    qdrant_curriculum_collection: str = field(default_factory=lambda: os.getenv("QDRANT_CURRICULUM_COLLECTION", "fpt_curriculum_map_v1"))
    llm_api_base_url: str | None = field(default_factory=lambda: os.getenv("LLM_API_BASE_URL"))
    llm_api_key: str | None = field(default_factory=lambda: os.getenv("LLM_API_KEY"))
    llm_model: str | None = field(default_factory=lambda: os.getenv("LLM_MODEL"))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "60")))
    bm25_syllabus_path: Path = field(init=False)
    bm25_curriculum_path: Path = field(init=False)
    offering_map_path: Path = field(init=False)
    eval_queries_path: Path = field(init=False)
    embedding_provider: str = field(default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "api"))
    embedding_local_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_LOCAL_MODEL", "google/embeddinggemma-300m"))
    vector_size: int = 768
    batch_size: int = field(default_factory=lambda: int(os.getenv("RAG_BATCH_SIZE", "32")))
    request_timeout_s: float = 60.0
    max_retries: int = 3
    top_k_default: int = 10
    rrf_k: int = 60

    def __post_init__(self) -> None:
        load_dotenv(self.project_root / ".env", override=False)
        self.embedding_api_base_url = os.getenv("EMBEDDING_API_BASE_URL", self.embedding_api_base_url)
        self.embedding_model_version = os.getenv("EMBEDDING_MODEL_VERSION", self.embedding_model_version)
        self.qdrant_url = os.getenv("QDRANT_URL", self.qdrant_url)
        self.qdrant_api_key = os.getenv("QDRANT_API_KEY", self.qdrant_api_key)
        self.qdrant_local_path = os.getenv("QDRANT_LOCAL_PATH") or self.qdrant_local_path
        self.qdrant_syllabus_collection = os.getenv("QDRANT_SYLLABUS_COLLECTION", self.qdrant_syllabus_collection)
        self.qdrant_curriculum_collection = os.getenv("QDRANT_CURRICULUM_COLLECTION", self.qdrant_curriculum_collection)
        self.llm_api_base_url = os.getenv("LLM_API_BASE_URL", self.llm_api_base_url)
        self.llm_api_key = os.getenv("LLM_API_KEY", self.llm_api_key)
        self.llm_model = os.getenv("LLM_MODEL", self.llm_model)
        self.llm_timeout_s = float(os.getenv("LLM_TIMEOUT_S", str(self.llm_timeout_s)))
        self.batch_size = int(os.getenv("RAG_BATCH_SIZE", str(self.batch_size)))
        self.embedding_provider = os.getenv("EMBEDDING_PROVIDER", self.embedding_provider).lower()
        self.embedding_local_model = os.getenv("EMBEDDING_LOCAL_MODEL", self.embedding_local_model)
        if self.embedding_provider not in {"api", "sentence-transformers"}:
            raise ValueError("EMBEDDING_PROVIDER must be api or sentence-transformers")
        if self.embedding_provider == "sentence-transformers" and not os.getenv("EMBEDDING_MODEL_VERSION"):
            self.embedding_model_version = f"{self.embedding_local_model}:sentence-transformers:v1"
        if self.batch_size < 1:
            raise ValueError("RAG_BATCH_SIZE must be positive")

        self.dataset_dir = self.project_root / "data" / "processed" / "v1"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.bm25_syllabus_path = self.artifacts_dir / "bm25_syllabus_detail.json"
        self.bm25_curriculum_path = self.artifacts_dir / "bm25_curriculum_map.json"
        self.offering_map_path = self.dataset_dir / "offering_map.jsonl"
        self.eval_queries_path = self.project_root / "evals" / "baseline_queries.json"
