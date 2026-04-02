from __future__ import annotations

import argparse
import json
from datetime import datetime

from fpt_rag.config import Settings
from fpt_rag.eval import evaluate_baseline
from fpt_rag.indexing import build_indexes
from fpt_rag.retrieval import HybridRetriever, print_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FPT curriculum retrieval baseline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("show-contract", help="Print retrieval contract")

    index_parser = subparsers.add_parser("index", help="Build Qdrant and BM25 indexes")
    index_parser.add_argument("--dataset-dir", default=None, help="Override dataset dir")

    query_parser = subparsers.add_parser("query", help="Run a hybrid retrieval query")
    query_parser.add_argument("--text", required=True, help="User query text")
    query_parser.add_argument("--top-k", type=int, default=None, help="Top K results")

    subparsers.add_parser("eval", help="Run baseline retrieval evaluation")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings()

    if args.command == "show-contract":
        print(print_contract(settings))
        return

    if args.command == "index":
        result = build_indexes(settings, dataset_dir=args.dataset_dir)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return

    if args.command == "query":
        retriever = HybridRetriever(settings)
        try:
            response = retriever.search(args.text, top_k=args.top_k)
            print(json.dumps({
                "parsed_query": {
                    "intent_group": response.parsed_query.intent_group,
                    "target_index": response.parsed_query.target_index,
                    "filters": response.parsed_query.filters.active_items(),
                },
                "latency_ms": response.latency_ms,
                "hits": [
                    {
                        "chunk_id": hit.chunk_id,
                        "score": hit.score,
                        "course_id": hit.payload.get("course_id"),
                        "major_code": hit.payload.get("major_code"),
                        "semester": hit.payload.get("semester"),
                        "chunk_type": hit.payload.get("chunk_type"),
                        "offering_key": hit.payload.get("parent_offering_key") or hit.payload.get("offering_key"),
                        "text": hit.text[:600],
                    }
                    for hit in response.hits
                ],
            }, ensure_ascii=True, indent=2))
        finally:
            retriever.close()
        return

    if args.command == "eval":
        result = evaluate_baseline(settings)
        eval_dir = settings.artifacts_dir / "evals"
        eval_dir.mkdir(parents=True, exist_ok=True)
        latest_path = eval_dir / "baseline_eval_latest.json"
        timestamp_path = eval_dir / f"baseline_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        serialized = json.dumps(result, ensure_ascii=True, indent=2)
        latest_path.write_text(serialized, encoding="utf-8")
        timestamp_path.write_text(serialized, encoding="utf-8")
        print(serialized)
        return


if __name__ == "__main__":
    main()
