from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def load_dataset_bundle(dataset_dir: Path) -> dict[str, list[dict[str, Any]]]:
    return {
        "curriculum": read_jsonl(dataset_dir / "curriculum_semester_chunks.jsonl"),
        "offering_map": read_jsonl(dataset_dir / "offering_map.jsonl"),
        "canonical_syllabus": read_jsonl(dataset_dir / "canonical_syllabus.jsonl"),
        "syllabus_detail": read_jsonl(dataset_dir / "syllabus_detail_chunks.jsonl"),
    }


def batched(items: list[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]
