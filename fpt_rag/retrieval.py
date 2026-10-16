from __future__ import annotations

import json
import re
import time
import unicodedata
from typing import Any

from .bm25_index import Bm25Index
from .config import Settings
from .dataset import ensure_dataset, read_jsonl
from .embedding_api import EmbeddingApiClient
from .models import ParsedQuery, QueryFilters, RetrievalHit, RetrievalResponse
from .qdrant_store import QdrantStore

COURSE_RE = re.compile(r"\b[A-Z]{2,}[A-Z0-9]*\d{3}[A-Z0-9.]*\b", re.IGNORECASE)
SEMESTER_RE = re.compile(r"(?:ky|ki|hoc ky|hoc ki|semester)\s*(\d{1,2})", re.IGNORECASE)
CHUNK_HINTS = {
    "learning outcomes": "learning_outcomes",
    "chuan dau ra": "learning_outcomes",
    "assessment": "assessments",
    "assessments": "assessments",
    "danh gia": "assessments",
    "materials": "materials",
    "tai lieu": "materials",
    "schedule": "schedule",
    "lich hoc": "schedule",
    "overview": "overview",
    "mo ta": "overview",
}
CURRICULUM_HINTS = (
    "hoc gi",
    "mon nao",
    "curriculum",
    "lo trinh",
    "chuong trinh hoc",
    "hoc ky",
    "ki",
    "ky",
)


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    normalized = stripped.replace(chr(273), "d").replace(chr(272), "D").lower()
    return " ".join(normalized.split())


class HybridRetriever:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        ensure_dataset(settings.dataset_dir, settings.project_root)
        self.embedding = EmbeddingApiClient(settings)
        self.qdrant = QdrantStore(settings)
        from .dataset import load_dataset_bundle
        if not settings.bm25_syllabus_path.exists() or not settings.bm25_curriculum_path.exists():
            bundle = load_dataset_bundle(settings.dataset_dir)
            if not settings.bm25_syllabus_path.exists():
                Bm25Index.build([
                    {"id": r["chunk_id"], "text": r["text"], "payload": r}
                    for r in bundle["syllabus_detail"]
                ]).save(settings.bm25_syllabus_path)
            if not settings.bm25_curriculum_path.exists():
                Bm25Index.build([
                    {"id": r["chunk_id"], "text": r["text"], "payload": r}
                    for r in bundle["curriculum"]
                ]).save(settings.bm25_curriculum_path)
        self.syllabus_bm25 = Bm25Index.load(settings.bm25_syllabus_path)
        self.curriculum_bm25 = Bm25Index.load(settings.bm25_curriculum_path)
        self.offering_by_key = {row["offering_key"]: row for row in read_jsonl(settings.offering_map_path)}
        self.known_majors = {row["major_code"] for row in self.offering_by_key.values()}
        self.known_combos = {row["combo_short_name"] for row in self.offering_by_key.values()}
        syllabus_docs = self.syllabus_bm25.docs
        self.title_to_course_ids: dict[str, set[str]] = {}
        self.course_to_major_semesters: dict[str, set[tuple[str, int]]] = {}
        self.known_course_ids: dict[str, str] = {}
        for doc in syllabus_docs:
            payload = doc.get("payload", {})
            course_id = payload.get("course_id")
            title_en = payload.get("title_en")
            title_vi = payload.get("title_vi")
            major_code = payload.get("major_code")
            semester = payload.get("semester")
            if course_id:
                self.known_course_ids.setdefault(course_id.lower(), course_id)
            if course_id and major_code is not None and semester is not None:
                self.course_to_major_semesters.setdefault(course_id, set()).add((major_code, semester))
            for title in (title_en, title_vi):
                if title and course_id:
                    key = normalize_text(title)
                    self.title_to_course_ids.setdefault(key, set()).add(course_id)

    def close(self) -> None:
        self.embedding.close()
        self.qdrant.close()

    def parse_query(self, text: str) -> ParsedQuery:
        normalized = " ".join(text.split())
        lowered = normalize_text(normalized)
        course_match = COURSE_RE.search(normalized)
        semester_match = SEMESTER_RE.search(lowered)
        inferred_course_id = None
        canonical_course_id = None
        if course_match:
            canonical_course_id = self.known_course_ids.get(course_match.group(0).lower(), course_match.group(0))
        if not course_match:
            matched_course_ids: set[str] = set()
            for title, course_ids in self.title_to_course_ids.items():
                if title in lowered:
                    matched_course_ids.update(course_ids)
            if len(matched_course_ids) == 1:
                inferred_course_id = next(iter(matched_course_ids))
        major_code = next((major for major in sorted(self.known_majors, key=len, reverse=True) if re.search(rf"\b{re.escape(major.lower())}\b", lowered)), None)
        combo_short_name = next((combo for combo in sorted(self.known_combos, key=len, reverse=True) if combo != "core" and normalize_text(combo) in lowered), None)
        chunk_type = next((mapped for hint, mapped in CHUNK_HINTS.items() if hint in lowered), None)
        filters = QueryFilters(
            course_id=canonical_course_id if canonical_course_id else inferred_course_id,
            major_code=major_code,
            semester=int(semester_match.group(1)) if semester_match else None,
            combo_short_name=combo_short_name,
            chunk_type=chunk_type,
        )
        curriculum_signal = any(hint in lowered for hint in CURRICULUM_HINTS)
        if curriculum_signal and filters.semester is not None and filters.course_id is None:
            target_index = "curriculum"
            intent_group = "curriculum"
        elif filters.chunk_type == "schedule":
            target_index = "syllabus_detail"
            intent_group = "schedule"
        elif filters.course_id or filters.chunk_type:
            target_index = "syllabus_detail"
            intent_group = "exact_filter"
        else:
            target_index = "syllabus_detail"
            intent_group = "semantic"
        return ParsedQuery(raw_text=text, normalized_text=normalized, filters=filters, target_index=target_index, intent_group=intent_group)

    def contextualize_query(self, text: str, history: list[dict[str, str]] | None = None) -> str:
        """Resolve basic course/semester references before searching the indexes."""
        if not history or not re.search(
            r"\b(mon do|mon nay|ky do|ky nay|that (?:course|semester)|that one)\b",
            normalize_text(text),
        ):
            return text
        current = self.parse_query(text)
        if current.filters.course_id or current.filters.semester is not None:
            return text
        for message in reversed(history):
            if message.get("role") != "user":
                continue
            previous = self.parse_query(message.get("content", ""))
            details = []
            if previous.filters.course_id:
                details.append(previous.filters.course_id)
            if previous.filters.major_code:
                details.append(previous.filters.major_code)
            if previous.filters.semester is not None:
                details.append(f"semester {previous.filters.semester}")
            if details:
                return text + " " + " ".join(details)
        return text

    def search(self, text: str, top_k: int | None = None, history: list[dict[str, str]] | None = None) -> RetrievalResponse:
        started = time.perf_counter()
        query = self.contextualize_query(text, history)
        parsed = self.parse_query(query)
        top_k = self.settings.top_k_default if top_k is None else top_k
        if top_k < 1:
            raise ValueError("top_k must be positive")
        metadata_filter = parsed.filters.active_items()
        collection = self.settings.qdrant_curriculum_collection if parsed.target_index == "curriculum" else self.settings.qdrant_syllabus_collection
        bm25_index = self.curriculum_bm25 if parsed.target_index == "curriculum" else self.syllabus_bm25
        bm25_hits = bm25_index.search(query, top_k=top_k * 3, metadata_filter=metadata_filter)
        query_vector = self.embedding.embed_query(query)
        vector_hits = self.qdrant.search(collection, query_vector=query_vector, top_k=top_k * 3, metadata_filter=metadata_filter)
        merged = self._rrf_merge(bm25_hits, vector_hits, top_k=top_k * 3)
        merged = self._rerank_hits(parsed, merged)[:top_k]
        latency_ms = (time.perf_counter() - started) * 1000
        return RetrievalResponse(parsed_query=parsed, hits=merged, latency_ms=latency_ms)

    def _rrf_merge(self, bm25_hits: list[tuple[dict[str, Any], float]], vector_hits: list[tuple[dict[str, Any], float]], top_k: int) -> list[RetrievalHit]:
        scores: dict[str, float] = {}
        docs: dict[str, dict[str, Any]] = {}
        for hits in (bm25_hits, vector_hits):
            ranked = sorted(hits, key=lambda item: item[1], reverse=True)
            for rank, (doc, _score) in enumerate(ranked, start=1):
                chunk_id = doc.get("chunk_id") or doc.get("payload", {}).get("chunk_id")
                if chunk_id is None:
                    continue
                docs[chunk_id] = doc
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (self.settings.rrf_k + rank)
        ordered = sorted(scores.items(), key=lambda item: (item[1], self._doc_priority(docs[item[0]])), reverse=True)[:top_k]
        results: list[RetrievalHit] = []
        for chunk_id, score in ordered:
            doc = docs[chunk_id]
            payload = dict(doc.get("payload", {}))
            payload.setdefault("chunk_id", chunk_id)
            offering_key = payload.get("parent_offering_key") or payload.get("offering_key")
            offering = self.offering_by_key.get(offering_key) if offering_key else None
            results.append(RetrievalHit(chunk_id=chunk_id, score=score, source="hybrid_rrf", text=doc.get("text") or payload.get("text", ""), payload=payload, offering=offering))
        return results

    def _rerank_hits(self, parsed: ParsedQuery, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        normalized_query = normalize_text(parsed.raw_text)

        def bonus(hit: RetrievalHit) -> tuple[int, float]:
            payload = hit.payload
            course_id = payload.get("course_id")
            title_en = normalize_text(payload.get("title_en", "")) if payload.get("title_en") else ""
            title_vi = normalize_text(payload.get("title_vi", "")) if payload.get("title_vi") else ""
            major_code = payload.get("major_code")
            semester = payload.get("semester")
            exact_title = int(bool(title_en and title_en in normalized_query) or bool(title_vi and title_vi in normalized_query))
            exact_course = int(parsed.filters.course_id is not None and course_id == parsed.filters.course_id)
            expected_major = int(parsed.filters.major_code is not None and major_code == parsed.filters.major_code)
            expected_semester = int(parsed.filters.semester is not None and semester == parsed.filters.semester)
            inferred_major_semester = 0
            if parsed.filters.course_id and course_id == parsed.filters.course_id:
                if (major_code, semester) in self.course_to_major_semesters.get(course_id, set()):
                    inferred_major_semester = 1
            return (exact_course * 8 + exact_title * 4 + expected_major * 2 + expected_semester + inferred_major_semester, hit.score)

        return sorted(hits, key=bonus, reverse=True)

    @staticmethod
    def _doc_priority(doc: dict[str, Any]) -> int:
        payload = doc.get("payload", {})
        chunk_type = payload.get("chunk_type")
        if chunk_type == "overview":
            return 3
        if chunk_type == "learning_outcomes":
            return 2
        if chunk_type == "materials":
            return 2
        if chunk_type == "assessments":
            return 2
        if chunk_type == "schedule":
            return 1
        return 0


def print_contract(settings: Settings) -> str:
    contract = {
        "input": {"query": "natural language text", "parsed_filters": ["course_id", "major_code", "semester", "combo_short_name", "chunk_type"]},
        "collections": {"curriculum": settings.qdrant_curriculum_collection, "syllabus_detail": settings.qdrant_syllabus_collection},
        "retrieval_flow": [
            "parse exact/filter intent first",
            "apply metadata pre-filter",
            "search BM25 and Qdrant sequentially",
            "merge with reciprocal rank fusion",
            "join offering_map for final context",
        ],
        "output": {"top_k_hits": ["chunk_id", "score", "text", "payload", "offering_context"]},
    }
    return json.dumps(contract, ensure_ascii=False, indent=2)
