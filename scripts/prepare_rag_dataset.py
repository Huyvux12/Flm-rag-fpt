import argparse
import datetime as dt
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


NULL_LIKE = {"", "none", "null", "n/a", "na", "-", "_"}


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip(" \t\n\"")
    if text.lower() in NULL_LIKE:
        return None
    return text


def clean_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def clean_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = clean_text(value)
    if text is None:
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def clean_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = clean_text(value)
    if text is None:
        return None
    text = text.replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_date_to_iso(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    text = clean_text(raw)
    if not text:
        return None, None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat(), text
        except ValueError:
            continue
    return None, text


def split_title_vi_en(metadata: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    title = clean_text(metadata.get("title"))
    english = clean_text(metadata.get("english_title"))
    course_name = clean_text(metadata.get("course_name_from_curriculum"))

    title_en = english
    title_vi = None

    candidate = course_name or title
    if candidate and "_" in candidate:
        parts = [p.strip() for p in candidate.split("_", 1)]
        if len(parts) == 2:
            if not title_en:
                title_en = clean_text(parts[0])
            title_vi = clean_text(parts[1])

    if not title_en:
        title_en = clean_text(title)

    return title_vi, title_en


def normalize_combo(combo_value: Any) -> str:
    combo = clean_text(combo_value)
    if not combo:
        return "core"
    return combo


def clean_list_of_dicts(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cleaned: Dict[str, Any] = {}
        for k, v in item.items():
            if isinstance(v, list):
                cleaned_list = [clean_text(x) for x in v]
                cleaned[k] = [x for x in cleaned_list if x is not None]
            elif isinstance(v, bool):
                cleaned[k] = v
            else:
                t = clean_text(v)
                cleaned[k] = t
        out.append(cleaned)
    return out


def estimate_keywords(text: str, top_n: int = 8) -> List[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{3,}", text.lower())
    stop = {
        "with", "from", "this", "that", "have", "will", "using", "chapter", "slide",
        "course", "student", "students", "offline", "online", "read", "review", "class"
    }
    freq: Dict[str, int] = defaultdict(int)
    for w in words:
        if w in stop:
            continue
        freq[w] += 1
    ranked = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
    return [k for k, _ in ranked[:top_n]]


def stable_hash(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_parquet(path: Path, rows: List[Dict[str, Any]]) -> bool:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception:
        return False

    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path.as_posix(), compression="zstd")
    return True


def build_overview_text(entry: Dict[str, Any]) -> str:
    lines = [
        f"Course ID: {entry.get('course_id')}",
        f"Title EN: {entry.get('title_en') or ''}",
        f"Title VI: {entry.get('title_vi') or ''}",
        f"Credits: {entry.get('credits')}",
        f"Prerequisites: {entry.get('prerequisites') or ''}",
        f"Description: {entry.get('description') or ''}",
        f"Student tasks: {entry.get('student_tasks') or ''}",
        f"Tools: {entry.get('tools') or ''}",
        f"Course type: {entry.get('course_type_guess') or ''}",
        f"Decision: {entry.get('decision_no') or ''}",
        f"Approved date: {entry.get('approved_date_iso') or entry.get('approved_date_raw') or ''}",
    ]
    return "\n".join(lines).strip()


def build_materials_text(materials: List[Dict[str, Any]]) -> str:
    if not materials:
        return "No materials provided."
    lines: List[str] = []
    for idx, m in enumerate(materials, start=1):
        lines.append(
            f"[{idx}] desc={m.get('description') or ''}; author={m.get('author') or ''}; "
            f"publisher={m.get('publisher') or ''}; edition={m.get('edition') or ''}; "
            f"isbn={m.get('isbn') or ''}; main={m.get('is_main_material') or ''}; "
            f"online={m.get('is_online') or ''}; note={m.get('note') or ''}"
        )
    return "\n".join(lines)


def build_assessment_text(assessments: List[Dict[str, Any]]) -> str:
    if not assessments:
        return "No assessments provided."
    lines: List[str] = []
    for idx, a in enumerate(assessments, start=1):
        lines.append(
            f"[{idx}] category={a.get('category') or ''}; type={a.get('type') or ''}; "
            f"weight={a.get('weight') or ''}; duration={a.get('duration') or ''}; "
            f"question_type={a.get('question_type') or ''}; grading_guide={a.get('grading_guide') or ''}; "
            f"completion_criteria={a.get('completion_criteria') or ''}; clos={','.join(a.get('clos') or [])}"
        )
    return "\n".join(lines)


def schedule_blocks(schedule: List[Dict[str, Any]], block_size: int = 4) -> List[List[Dict[str, Any]]]:
    if not schedule:
        return []
    return [schedule[i:i + block_size] for i in range(0, len(schedule), block_size)]


def build_schedule_text(items: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for idx, s in enumerate(items, start=1):
        lo = s.get("learning_outcomes") or []
        lo_text = ", ".join(lo) if isinstance(lo, list) else str(lo)
        lines.append(
            f"Session {idx}: {s.get('session') or ''}\n"
            f"Topic: {s.get('topic') or ''}; Teaching type: {s.get('teaching_type') or ''}; LO: {lo_text}\n"
            f"ITU: {s.get('itu') or ''}\nMaterials: {s.get('materials') or ''}\n"
            f"Tasks: {s.get('tasks') or ''}\nDownload: {s.get('download_link') or ''}\nURLs: {s.get('urls') or ''}"
        )
    return "\n\n".join(lines)


def header_text(offering: Dict[str, Any], chunk_type: str, extra: Optional[str] = None) -> str:
    base = (
        f"[major={offering['major_code']} | semester={offering['semester']} | "
        f"course_id={offering['course_id']} | syllabus_id={offering['syllabus_id']} | "
        f"title_en={offering.get('title_en') or ''} | title_vi={offering.get('title_vi') or ''} | "
        f"combo={offering['combo_short_name']} | chunk_type={chunk_type}"
    )
    if extra:
        base += f" | {extra}"
    return base + "]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse/Clean/Chunk curriculum JSON files for RAG")
    parser.add_argument("--input-dir", default="data", help="Input directory containing flm_data_*.json")
    parser.add_argument("--output-dir", default="data/processed/v1", help="Output directory")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("flm_data_*.json"))
    if not files:
        raise SystemExit("No input files found matching flm_data_*.json")

    now_iso = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    schema_version = "v1.0.0"

    offerings: List[Dict[str, Any]] = []
    curriculum_groups: Dict[Tuple[str, int, str], Dict[str, Any]] = {}

    canonical_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for file_path in files:
        with file_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        major_code = clean_text(payload.get("major_code_input")) or file_path.stem.replace("flm_data_", "")
        curriculum_title = clean_text(payload.get("curriculum_title_on_page"))
        curriculum_url = clean_text(payload.get("curriculum_url"))
        syllabuses = payload.get("syllabuses") or []

        for syl in syllabuses:
            metadata = syl.get("metadata") or {}

            course_id = clean_text(metadata.get("course_id") or metadata.get("subject_code_on_page"))
            syllabus_id = clean_text(metadata.get("syllabus_id") or metadata.get("syllabus_id_from_url"))
            if not course_id or not syllabus_id:
                continue

            semester = clean_int(metadata.get("semester_from_curriculum")) or -1
            combo_short_name = normalize_combo(metadata.get("combo_short_name_from_curriculum"))
            combo_name = clean_text(metadata.get("combo_name_from_curriculum"))

            title_vi, title_en = split_title_vi_en(metadata)
            approved_date_iso, approved_date_raw = parse_date_to_iso(metadata.get("approved_date"))

            materials = clean_list_of_dicts(syl.get("materials") or [])
            learning_outcomes = clean_list_of_dicts(syl.get("learning_outcomes") or [])
            assessments = clean_list_of_dicts(syl.get("assessments") or [])
            schedule = clean_list_of_dicts(syl.get("schedule") or [])

            canonical_payload = {
                "course_id": course_id,
                "title_vi": title_vi,
                "title_en": title_en,
                "credits": clean_float(metadata.get("credits")),
                "prerequisites": clean_text(metadata.get("prerequisites")),
                "description": clean_text(metadata.get("description")),
                "student_tasks": clean_text(metadata.get("student_tasks")),
                "tools": clean_text(metadata.get("tools")),
                "course_type_guess": clean_text(metadata.get("course_type_guess")),
                "materials": materials,
                "learning_outcomes": learning_outcomes,
                "assessments": assessments,
                "schedule": schedule,
            }
            content_hash = stable_hash(canonical_payload)
            pair_key = (syllabus_id, content_hash)
            canonical_key = f"{syllabus_id}|{content_hash[:8]}"

            if pair_key not in canonical_by_pair:
                canonical_by_pair[pair_key] = {
                    "canonical_syllabus_key": canonical_key,
                    "syllabus_id": syllabus_id,
                    "content_hash": content_hash,
                    "course_id": course_id,
                    "title_vi": title_vi,
                    "title_en": title_en,
                    "credits": clean_float(metadata.get("credits")),
                    "prerequisites": clean_text(metadata.get("prerequisites")),
                    "description": clean_text(metadata.get("description")),
                    "student_tasks": clean_text(metadata.get("student_tasks")),
                    "tools": clean_text(metadata.get("tools")),
                    "course_type_guess": clean_text(metadata.get("course_type_guess")),
                    "decision_no": clean_text(metadata.get("decision_no")),
                    "approved_date_iso": approved_date_iso,
                    "approved_date_raw": approved_date_raw,
                    "is_active": clean_bool(metadata.get("is_active")),
                    "is_approved": clean_bool(metadata.get("is_approved")),
                    "materials": materials,
                    "learning_outcomes": learning_outcomes,
                    "assessments": assessments,
                    "schedule": schedule,
                    "offering_keys": [],
                    "source_files": [file_path.name],
                    "schema_version": schema_version,
                    "generated_at": now_iso,
                }
            else:
                if file_path.name not in canonical_by_pair[pair_key]["source_files"]:
                    canonical_by_pair[pair_key]["source_files"].append(file_path.name)

            offering_key = "|".join([major_code, course_id, syllabus_id, str(semester), combo_short_name])
            canonical_by_pair[pair_key]["offering_keys"].append(offering_key)

            offering = {
                "offering_key": offering_key,
                "canonical_syllabus_key": canonical_key,
                "major_code": major_code,
                "curriculum_title": curriculum_title,
                "curriculum_url": curriculum_url,
                "course_id": course_id,
                "subject_code": clean_text(metadata.get("subject_code_on_page")) or course_id,
                "syllabus_id": syllabus_id,
                "semester": semester,
                "combo_short_name": combo_short_name,
                "combo_name": combo_name,
                "title_vi": title_vi,
                "title_en": title_en,
                "approved_date_iso": approved_date_iso,
                "approved_date_raw": approved_date_raw,
                "decision_no": clean_text(metadata.get("decision_no")),
                "is_active": clean_bool(metadata.get("is_active")),
                "source_file": file_path.name,
                "schema_version": schema_version,
                "generated_at": now_iso,
            }
            offerings.append(offering)

            group_key = (major_code, semester, combo_short_name)
            if group_key not in curriculum_groups:
                curriculum_groups[group_key] = {
                    "major_code": major_code,
                    "semester": semester,
                    "combo_short_name": combo_short_name,
                    "curriculum_title": curriculum_title,
                    "curriculum_url": curriculum_url,
                    "courses": [],
                }
            curriculum_groups[group_key]["courses"].append({
                "course_id": course_id,
                "title_en": title_en,
                "title_vi": title_vi,
                "offering_key": offering_key,
                "canonical_syllabus_key": canonical_key,
            })

    canonical_rows = sorted(canonical_by_pair.values(), key=lambda x: x["canonical_syllabus_key"])

    offering_by_key = {o["offering_key"]: o for o in offerings}

    syllabus_chunks: List[Dict[str, Any]] = []

    for canon in canonical_rows:
        for offering_key in sorted(set(canon["offering_keys"])):
            offering = offering_by_key.get(offering_key)
            if not offering:
                continue

            base_meta = {
                "parent_offering_key": offering_key,
                "canonical_syllabus_key": canon["canonical_syllabus_key"],
                "course_cluster_key": offering["course_id"],
                "major_code": offering["major_code"],
                "semester": offering["semester"],
                "combo_short_name": offering["combo_short_name"],
                "course_id": offering["course_id"],
                "subject_code": offering["subject_code"],
                "syllabus_id": offering["syllabus_id"],
                "title_en": offering["title_en"],
                "title_vi": offering["title_vi"],
                "approved_date_iso": offering["approved_date_iso"],
                "approved_date_raw": offering["approved_date_raw"],
                "decision_no": offering["decision_no"],
                "is_active": offering["is_active"],
                "schema_version": schema_version,
                "generated_at": now_iso,
            }

            overview_text = build_overview_text(canon)
            syllabus_chunks.append({
                **base_meta,
                "chunk_id": f"{offering_key}|overview|01",
                "chunk_type": "overview",
                "chunk_seq": 1,
                "session_start": None,
                "session_end": None,
                "mentioned_clos": [],
                "keywords": estimate_keywords(overview_text),
                "text": header_text(offering, "overview") + "\n" + overview_text,
            })

            lo_items = canon.get("learning_outcomes") or []
            if lo_items:
                for idx, lo in enumerate(lo_items, start=1):
                    lo_id = clean_text(lo.get("id")) or f"LO{idx}"
                    lo_detail = clean_text(lo.get("details")) or ""
                    lo_text = f"{lo_id}: {lo_detail}".strip()
                    syllabus_chunks.append({
                        **base_meta,
                        "chunk_id": f"{offering_key}|learning_outcomes|{idx:02d}",
                        "chunk_type": "learning_outcomes",
                        "chunk_seq": idx,
                        "session_start": None,
                        "session_end": None,
                        "mentioned_clos": [lo_id],
                        "keywords": estimate_keywords(lo_text),
                        "text": header_text(offering, "learning_outcomes", f"clo={lo_id}") + "\n" + lo_text,
                    })
            else:
                syllabus_chunks.append({
                    **base_meta,
                    "chunk_id": f"{offering_key}|learning_outcomes|01",
                    "chunk_type": "learning_outcomes",
                    "chunk_seq": 1,
                    "session_start": None,
                    "session_end": None,
                    "mentioned_clos": [],
                    "keywords": [],
                    "text": header_text(offering, "learning_outcomes") + "\nNo learning outcomes provided.",
                })

            assess_text = build_assessment_text(canon.get("assessments") or [])
            assess_clos: List[str] = []
            for a in canon.get("assessments") or []:
                for c in (a.get("clos") or []):
                    cc = clean_text(c)
                    if cc:
                        assess_clos.append(cc)
            syllabus_chunks.append({
                **base_meta,
                "chunk_id": f"{offering_key}|assessments|01",
                "chunk_type": "assessments",
                "chunk_seq": 1,
                "session_start": None,
                "session_end": None,
                "mentioned_clos": sorted(set(assess_clos)),
                "keywords": estimate_keywords(assess_text),
                "text": header_text(offering, "assessments") + "\n" + assess_text,
            })

            materials_text = build_materials_text(canon.get("materials") or [])
            syllabus_chunks.append({
                **base_meta,
                "chunk_id": f"{offering_key}|materials|01",
                "chunk_type": "materials",
                "chunk_seq": 1,
                "session_start": None,
                "session_end": None,
                "mentioned_clos": [],
                "keywords": estimate_keywords(materials_text),
                "text": header_text(offering, "materials") + "\n" + materials_text,
            })

            schedule = canon.get("schedule") or []
            blocks = schedule_blocks(schedule, block_size=4)
            if blocks:
                for idx, block in enumerate(blocks, start=1):
                    s_start = (idx - 1) * 4 + 1
                    s_end = s_start + len(block) - 1
                    block_text = build_schedule_text(block)
                    teaching = sorted(set([clean_text(x.get("teaching_type")) for x in block if clean_text(x.get("teaching_type"))]))
                    syllabus_chunks.append({
                        **base_meta,
                        "chunk_id": f"{offering_key}|schedule|{idx:02d}",
                        "chunk_type": "schedule",
                        "chunk_seq": idx,
                        "session_start": s_start,
                        "session_end": s_end,
                        "mentioned_clos": teaching,
                        "keywords": estimate_keywords(block_text),
                        "text": header_text(offering, "schedule", f"sessions={s_start}-{s_end}") + "\n" + block_text,
                    })
            else:
                syllabus_chunks.append({
                    **base_meta,
                    "chunk_id": f"{offering_key}|schedule|01",
                    "chunk_type": "schedule",
                    "chunk_seq": 1,
                    "session_start": None,
                    "session_end": None,
                    "mentioned_clos": [],
                    "keywords": [],
                    "text": header_text(offering, "schedule") + "\nNo schedule provided.",
                })

    curriculum_rows: List[Dict[str, Any]] = []
    for (major_code, semester, combo), group in sorted(curriculum_groups.items(), key=lambda x: x[0]):
        courses = sorted(group["courses"], key=lambda c: c["course_id"])
        lines = [
            f"Major: {major_code}",
            f"Semester: {semester}",
            f"Combo: {combo}",
            f"Curriculum: {group.get('curriculum_title') or ''}",
            f"URL: {group.get('curriculum_url') or ''}",
            "Courses:",
        ]
        for c in courses:
            lines.append(f"- {c['course_id']}: {c.get('title_en') or ''} | {c.get('title_vi') or ''}")

        curriculum_rows.append({
            "chunk_id": f"{major_code}|semester|{semester}|{combo}",
            "major_code": major_code,
            "semester": semester,
            "combo_short_name": combo,
            "course_count": len(courses),
            "course_ids": [c["course_id"] for c in courses],
            "courses": courses,
            "curriculum_title": group.get("curriculum_title"),
            "curriculum_url": group.get("curriculum_url"),
            "schema_version": schema_version,
            "generated_at": now_iso,
            "text": "\n".join(lines),
        })

    offering_rows = sorted(offerings, key=lambda x: x["offering_key"])

    p_curr_jsonl = output_dir / "curriculum_semester_chunks.jsonl"
    p_offer_jsonl = output_dir / "offering_map.jsonl"
    p_canon_jsonl = output_dir / "canonical_syllabus.jsonl"
    p_chunk_jsonl = output_dir / "syllabus_detail_chunks.jsonl"

    n_curr = write_jsonl(p_curr_jsonl, curriculum_rows)
    n_offer = write_jsonl(p_offer_jsonl, offering_rows)
    n_canon = write_jsonl(p_canon_jsonl, canonical_rows)
    n_chunk = write_jsonl(p_chunk_jsonl, syllabus_chunks)

    parquet_written = {
        "curriculum_semester_chunks.parquet": write_parquet(output_dir / "curriculum_semester_chunks.parquet", curriculum_rows),
        "offering_map.parquet": write_parquet(output_dir / "offering_map.parquet", offering_rows),
        "canonical_syllabus.parquet": write_parquet(output_dir / "canonical_syllabus.parquet", canonical_rows),
        "syllabus_detail_chunks.parquet": write_parquet(output_dir / "syllabus_detail_chunks.parquet", syllabus_chunks),
    }

    manifest = {
        "schema_version": schema_version,
        "generated_at": now_iso,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "input_files": [f.name for f in files],
        "stats": {
            "curriculum_semester_chunks": n_curr,
            "offering_map": n_offer,
            "canonical_syllabus": n_canon,
            "syllabus_detail_chunks": n_chunk,
        },
        "parquet_written": parquet_written,
    }

    with (output_dir / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
