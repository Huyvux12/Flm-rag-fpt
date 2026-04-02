from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class QueryFilters:
    course_id: str | None = None
    major_code: str | None = None
    semester: int | None = None
    combo_short_name: str | None = None
    chunk_type: str | None = None

    def active_items(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "course_id": self.course_id,
                "major_code": self.major_code,
                "semester": self.semester,
                "combo_short_name": self.combo_short_name,
                "chunk_type": self.chunk_type,
            }.items()
            if value not in (None, "")
        }


@dataclass(slots=True)
class ParsedQuery:
    raw_text: str
    normalized_text: str
    filters: QueryFilters
    target_index: str
    intent_group: str


@dataclass(slots=True)
class RetrievalHit:
    chunk_id: str
    score: float
    source: str
    text: str
    payload: dict[str, Any]
    offering: dict[str, Any] | None = None


@dataclass(slots=True)
class RetrievalResponse:
    parsed_query: ParsedQuery
    hits: list[RetrievalHit] = field(default_factory=list)
    latency_ms: float = 0.0
