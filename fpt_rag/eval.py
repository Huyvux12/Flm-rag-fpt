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
            recalls.append(1.0 if any(relevant) else 0.0)
            precisions.append(sum(relevant) / max(len(relevant), 1))
            rr = 0.0
            for idx, rel in enumerate(relevant, start=1):
                if rel:
                    rr = 1.0 / idx
                    break
            rr_scores.append(rr)
            ideal = sorted(relevant, reverse=True)
            ndcgs.append(_dcg(relevant) / _dcg(ideal) if _dcg(ideal) else 0.0)

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
        "Recall@10": mean(recalls) if recalls else 0.0,
        "MRR@10": mean(rr_scores) if rr_scores else 0.0,
        "nDCG@10": mean(ndcgs) if ndcgs else 0.0,
        "Precision@10": mean(precisions) if precisions else 0.0,
        "major_semester_accuracy": mean(major_semester_hits) if major_semester_hits else 0.0,
        "course_id_exact_match_rate": mean(course_exact_hits) if course_exact_hits else 0.0,
        "P95_latency_ms": sorted_latencies[idx95] if sorted_latencies else 0.0,
        "failure_cases": failures,
        "query_count": len(queries),
    }
