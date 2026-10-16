from pathlib import Path
from types import SimpleNamespace

import pytest

from fpt_rag.bm25_index import Bm25Index, tokenize
from fpt_rag.config import Settings
from fpt_rag.dataset import ensure_dataset
from fpt_rag.models import QueryFilters
from fpt_rag.retrieval import HybridRetriever


def test_vietnamese_tokenization():
    assert tokenize("Tài liệu môn DPL302m là gì?") == ["tài", "liệu", "môn", "dpl302m", "là", "gì"]


def test_bm25_zero_scores_are_not_returned():
    idx = Bm25Index.build([{"text": "alpha beta", "payload": {}}, {"text": "gamma delta", "payload": {}}])
    assert idx.search("utterlyunrelated", top_k=5) == []


def test_settings_dataset_path():
    settings = Settings()
    assert settings.dataset_dir == settings.project_root / "data" / "processed" / "v1"


def test_dataset_bootstrap_no_sources(tmp_path):
    (tmp_path / "data").mkdir()
    with pytest.raises(FileNotFoundError):
        ensure_dataset(tmp_path / "data" / "processed" / "v1", tmp_path)


def test_contextual_followup_rewrites_course():
    r = object.__new__(HybridRetriever)
    r.known_course_ids = {"ail303m": "AIL303m"}
    r.known_majors = {"AI"}
    r.known_combos = {"core"}
    r.title_to_course_ids = {}
    r.course_to_major_semesters = {}
    rewritten = r.contextualize_query("Tai lieu mon do?", [{"role": "user", "content": "AIL303m hoc gi?"}])
    assert "AIL303m" in rewritten


def test_invalid_top_k():
    r = object.__new__(HybridRetriever)
    r.settings = SimpleNamespace(top_k_default=10)
    r.contextualize_query = lambda text, history=None: text
    r.parse_query = lambda text: SimpleNamespace(filters=QueryFilters(), target_index="syllabus_detail")
    with pytest.raises(ValueError, match="top_k"):
        r.search("hello", top_k=0)
