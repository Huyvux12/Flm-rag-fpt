from __future__ import annotations

import json
import math
from statistics import mean
from typing import Any

from .config import Settings
from .retrieval import HybridRetriever


def _dcg(relevances: list[int]) -> float:
    score = 0.0
    for idx, rel in enumerate(relevances, start=1):
        if rel <= 0:
            continue
        score += rel / math.log2(idx + 1)
    return score


def evaluate_baseline(settings: Settings) -> dict[str, Any]:
    with settings.eval_queries_path.open("r", encoding="utf-8") as handle:
        queries = json.load(handle)

    retriever = HybridRetriever(settings)
    top_k = settings.top_k_default
    recalls: list[float] = []
    hit_rates: list[float] = []
    rr_scores: list[float] = []
    ndcgs: list[float] = []
    precisions: list[float] = []
    major_semester_hits: list[float] = []
    course_exact_hits: list[float] = []
    latencies: list[float] = []
    failures: list[dict[str, Any]] = []

    try:
        for item in queries:
            response = retriever.search(item["query"], top_k=top_k)
            latencies.append(response.latency_ms)
            hits = response.hits
            relevant = []
            for hit in hits:
                matches_course = item.get("expected_course_id") is None or hit.payload.get("course_id") == item.get("expected_course_id")
                matches_major = item.get("expected_major_code") is None or hit.payload.get("major_code") == item.get("expected_major_code")
                matches_semester = item.get("expected_semester") is None or hit.payload.get("semester") == item.get("expected_semester")
                matches_chunk = item.get("expected_chunk_type") is None or hit.payload.get("chunk_type") == item.get("expected_chunk_type")
                relevant.append(1 if all((matches_course, matches_major, matches_semester, matches_chunk)) else 0)
            all_docs = (
                retriever.curriculum_bm25.docs if response.parsed_query.target_index == "curriculum"
                else retriever.syllabus_bm25.docs
            )

            def is_relevant(payload: dict[str, Any]) -> bool:
                return (
                    (item.get("expected_course_id") is None or payload.get("course_id") == item["expected_course_id"])
                    and (item.get("expected_major_code") is None or payload.get("major_code") == item["expected_major_code"])
                    and (item.get("expected_semester") is None or payload.get("semester") == item["expected_semester"])
                    and (item.get("expected_chunk_type") is None or payload.get("chunk_type") == item["expected_chunk_type"])
                )

            total_relevant = sum(is_relevant(doc.get("payload", {})) for doc in all_docs)
            recalls.append(sum(relevant) / total_relevant if total_relevant else 0.0)
            hit_rates.append(1.0 if any(relevant) else 0.0)
            precisions.append(sum(relevant) / top_k)
            rr = 0.0
            for idx, rel in enumerate(relevant, start=1):
                if rel:
                    rr = 1.0 / idx
                    break
            rr_scores.append(rr)
            ideal = [1] * min(top_k, total_relevant)
            ndcgs.append(_dcg(relevant) / _dcg(ideal) if ideal else 0.0)

            top_hit = hits[0] if hits else None
            if top_hit:
                major_semester_hits.append(1.0 if (item.get("expected_major_code") is None or top_hit.payload.get("major_code") == item.get("expected_major_code")) and (item.get("expected_semester") is None or top_hit.payload.get("semester") == item.get("expected_semester")) else 0.0)
                course_exact_hits.append(1.0 if item.get("expected_course_id") is None or top_hit.payload.get("course_id") == item.get("expected_course_id") else 0.0)
            else:
                major_semester_hits.append(0.0)
                course_exact_hits.append(0.0)

            if not any(relevant):
                failures.append({
                    "query": item["query"],
                    "expected": item,
                    "top_hit": hits[0].payload if hits else None,
                })
    finally:
        retriever.close()

    sorted_latencies = sorted(latencies)
    idx95 = max(0, math.ceil(len(sorted_latencies) * 0.95) - 1)
    return {
        f"Recall@{top_k}": mean(recalls) if recalls else 0.0,
        f"HitRate@{top_k}": mean(hit_rates) if hit_rates else 0.0,
        f"MRR@{top_k}": mean(rr_scores) if rr_scores else 0.0,
        f"nDCG@{top_k}": mean(ndcgs) if ndcgs else 0.0,
        f"Precision@{top_k}": mean(precisions) if precisions else 0.0,
        "relevance_definition": "metadata proxy (not human relevance judgments)",
        "major_semester_accuracy": mean(major_semester_hits) if major_semester_hits else 0.0,
        "course_id_exact_match_rate": mean(course_exact_hits) if course_exact_hits else 0.0,
        "P95_latency_ms": sorted_latencies[idx95] if sorted_latencies else 0.0,
        "failure_cases": failures,
        "query_count": len(queries),
    }
