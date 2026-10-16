from __future__ import annotations

import json
import subprocess
import sys
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


def ensure_dataset(dataset_dir: Path, project_root: Path) -> None:
    """Rebuild missing derived JSONL files from the checked-in raw FLM JSON sources."""
    required = (
        "curriculum_semester_chunks.jsonl", "offering_map.jsonl",
        "canonical_syllabus.jsonl", "syllabus_detail_chunks.jsonl",
    )
    if all((dataset_dir / name).is_file() for name in required):
        return
    raw_dir = project_root / "data"
    if not list(raw_dir.glob("flm_data_*.json")):
        raise FileNotFoundError(f"No prepared dataset in {dataset_dir} and no raw data in {raw_dir}")
    subprocess.run(
        [sys.executable, str(project_root / "scripts" / "prepare_rag_dataset.py"),
         "--input-dir", str(raw_dir), "--output-dir", str(dataset_dir)],
        check=True,
    )
    missing = [name for name in required if not (dataset_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Dataset generation did not produce: {missing}")


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
