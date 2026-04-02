﻿---
license: mit
language:
- vi
- en
tags:
- education
- curriculum
- rag
- vietnamese
pretty_name: FPT University Curriculum RAG Chunks v1
size_categories:
- 10K<n<100K
---

# FPT University Curriculum RAG Chunks (v1)

Bộ dữ liệu đã được parse + clean + chunk từ các file `flm_data_*.json` để dùng cho RAG, semantic search và metadata filtering.

Phiên bản này tập trung vào **data chuẩn hóa** (chưa bao gồm retrieval runtime).

## Nguồn dữ liệu

- Nguồn gốc: dữ liệu curriculum/syllabus được thu thập từ FLM.
- Input gốc: 15 file JSON trong thư mục `data/`.
- Thời điểm tạo bản này: xem `generated_at` trong `manifest.json`.

## Cấu trúc thư mục

- `curriculum_semester_chunks.jsonl`
- `curriculum_semester_chunks.parquet`
- `offering_map.jsonl`
- `offering_map.parquet`
- `canonical_syllabus.jsonl`
- `canonical_syllabus.parquet`
- `syllabus_detail_chunks.jsonl`
- `syllabus_detail_chunks.parquet`
- `manifest.json`

## Thống kê nhanh (v1)

Từ `manifest.json`:

- `curriculum_semester_chunks`: 227
- `offering_map`: 602
- `canonical_syllabus`: 243
- `syllabus_detail_chunks`: 13,519

## Thiết kế dữ liệu

### 1) `curriculum_semester_chunks`

Mỗi record đại diện cho một cụm chương trình theo `(major_code, semester, combo_short_name)`.

Dùng tốt cho câu hỏi lộ trình như:
- "Ngành AI kỳ 4 học gì?"
- "SE kỳ 8 có môn nào?"

Trường chính:
- `chunk_id`
- `major_code`
- `semester`
- `combo_short_name`
- `course_ids`
- `courses`
- `text`

### 2) `offering_map`

Map ngữ cảnh mở môn theo ngành/kỳ/định hướng.

Khóa chính:
- `offering_key = major_code|course_id|syllabus_id|semester|combo_short_name`

Dùng để đảm bảo truy xuất đúng context (tránh nhầm cùng `course_id` giữa các ngành).

Trường chính:
- `offering_key`
- `canonical_syllabus_key`
- `major_code`
- `course_id`
- `syllabus_id`
- `semester`
- `combo_short_name`
- `title_vi`, `title_en`

### 3) `canonical_syllabus`

Lớp canonical để giảm duplicate nội dung syllabus.

Khóa canonical:
- `canonical_syllabus_key = syllabus_id|content_hash8`

Trường chính:
- metadata môn học chuẩn hóa
- `materials`, `learning_outcomes`, `assessments`, `schedule`
- `offering_keys` (list các offering đang dùng canonical này)

### 4) `syllabus_detail_chunks`

Các chunk chi tiết để embedding/search.

`chunk_type` hiện có:
- `overview`
- `learning_outcomes`
- `assessments`
- `materials`
- `schedule`

Chunk mang đủ metadata để filter sau này:
- `major_code`, `semester`, `course_id`, `syllabus_id`
- `parent_offering_key`, `canonical_syllabus_key`
- `chunk_type`, `chunk_seq`
- `session_start`, `session_end` (với schedule)
- `mentioned_clos`, `keywords`

## Quy tắc clean/chunk chính

- Chuẩn hóa bool/int/float/date từ text nguồn.
- Chuẩn hóa text: trim, bỏ ký tự rác, thống nhất null-like values.
- `combo_short_name` rỗng được thay bằng `core`.
- Chunk theo section thay vì chunk theo file ngành.
- `schedule` được chia block 4 sessions/chunk.
- Mỗi chunk có header ngữ cảnh để tăng độ chính xác retrieval.

## Recommended Skill Stack cho project này

### Core
- `rag-engineer`
- `hybrid-search-implementation`
- `embedding-strategies`
- `vector-database-engineer`
- `llm-evaluation`
- `python-pro`

### Architecture/Production
- `ai-engineer`
- `software-architecture`
- `database-architect`
- `hugging-face-datasets`

## Cách load nhanh bằng Hugging Face Datasets

```python
from datasets import load_dataset

# Khi dataset đã được upload lên HF Hub:
# ví dụ repo_id = "your-username/fpt-curriculum-rag-v1"

ds_chunks = load_dataset("your-username/fpt-curriculum-rag-v1", data_files="syllabus_detail_chunks.parquet")
ds_offering = load_dataset("your-username/fpt-curriculum-rag-v1", data_files="offering_map.parquet")

print(ds_chunks["train"].num_rows)
print(ds_chunks["train"].column_names)
```

## Gợi ý dùng cho RAG (giai đoạn sau)

- Exact/filter trước trên `course_id`, `major_code`, `semester`, `combo_short_name`.
- Vector search trên `syllabus_detail_chunks`.
- Join ngược qua `offering_map` để trả lời đúng ngữ cảnh ngành/kỳ.

## Phiên bản và khả năng tái lập

- `schema_version`: xem trong `manifest.json`.
- Script tạo dữ liệu: `scripts/prepare_rag_dataset.py`.
- Có thể regenerate bằng cách chạy script trên thư mục `data/`.

## Lưu ý sử dụng và trách nhiệm

- Dữ liệu có thể thay đổi theo từng đợt cập nhật syllabus/curriculum từ hệ thống nguồn.
- Nên kiểm tra lại thông tin chính thức của nhà trường khi dùng cho quyết định học tập quan trọng.
- Người dùng dataset chịu trách nhiệm tuân thủ điều khoản và chính sách dữ liệu của nguồn phát hành.
