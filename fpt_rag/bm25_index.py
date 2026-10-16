from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

TOKEN_RE = re.compile(r"[^\W_]+(?:[_.-][^\W_]+)*", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


@dataclass(slots=True)
class Bm25Index:
    docs: list[dict[str, Any]]
    tokenized_corpus: list[list[str]]
    engine: BM25Okapi = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.engine = BM25Okapi(self.tokenized_corpus or [["empty"]])

    @classmethod
    def build(cls, docs: list[dict[str, Any]]) -> "Bm25Index":
        return cls(docs=docs, tokenized_corpus=[tokenize(doc["text"]) for doc in docs])

    @classmethod
    def load(cls, path: Path) -> "Bm25Index":
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls(docs=payload["docs"], tokenized_corpus=payload["tokenized_corpus"])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump({"docs": self.docs, "tokenized_corpus": self.tokenized_corpus}, handle, ensure_ascii=False)

    def search(self, query: str, top_k: int, metadata_filter: dict[str, Any] | None = None) -> list[tuple[dict[str, Any], float]]:
        if top_k < 1:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        raw_scores = self.engine.get_scores(tokens)
        scored: list[tuple[dict[str, Any], float]] = []
        for doc, score in zip(self.docs, raw_scores, strict=True):
            if metadata_filter and not _matches_filter(doc.get("payload", {}), metadata_filter):
                continue
            if not math.isfinite(float(score)) or score <= 0:
                continue
            scored.append((doc, float(score)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


def _matches_filter(payload: dict[str, Any], metadata_filter: dict[str, Any]) -> bool:
    for key, expected in metadata_filter.items():
        if payload.get(key) != expected:
            return False
    return True
