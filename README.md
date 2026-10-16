# FPT Curriculum RAG Baseline

Retrieval-first RAG baseline for FPT University curriculum and syllabus data.

## What is included

- Qdrant indexing for `curriculum_semester_chunks` and `syllabus_detail_chunks`
- BM25 artifacts for keyword retrieval
- Hybrid retrieval with metadata filters and Reciprocal Rank Fusion
- `offering_map` join to preserve major, semester, and combo context
- Streamlit chat demo with short-term conversational memory
- Baseline evaluation queries and retrieval metrics

## Project layout

- `fpt_rag/`: retrieval, indexing, evaluation, and client code
- `streamlit_app.py`: demo chat application
- `main.py`: CLI for contract display, indexing, querying, and evaluation
- `evals/baseline_queries.json`: evaluation inputs
- `artifacts/bm25_*.json`: BM25 artifacts used by the demo runtime
- `notebooks/colab_qdrant_embeddinggemma_index.ipynb`: optional Colab workflow for indexing

## Environment

Copy `.env.example` to `.env` and fill in the values you want to use locally.

Important variables:

- `EMBEDDING_API_BASE_URL`
- `EMBEDDING_MODEL_VERSION`
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `QDRANT_SYLLABUS_COLLECTION`
- `QDRANT_CURRICULUM_COLLECTION`
- `LLM_API_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`
- `LLM_TIMEOUT_S`
- `RAG_BATCH_SIZE`

## Install

```bash
uv sync
```

## Run the CLI

```bash
uv run python main.py show-contract
uv run python main.py query --text "AI ky 4 hoc gi?"
uv run python main.py eval
```

## Run the demo app

```bash
uv run streamlit run streamlit_app.py
```

## Notes

- The repo keeps BM25 artifacts in `artifacts/` so the demo can run without rebuilding them first.
- Local runtime state such as `.env`, local Qdrant files, and generated eval outputs should not be committed.
- If you change embedding behavior or model version, rebuild indexes before trusting final retrieval metrics.

## Rebuild missing derived data and run

The tracked raw `data/flm_data_*.json` files are the source of truth. Derived syllabus
chunks and BM25 artifacts may not be checked into Git. The app/CLI regenerate missing
JSONL and BM25 files on first use; this requires enough disk space.

```bash
uv sync --extra test
uv run python scripts/prepare_rag_dataset.py --input-dir data --output-dir data/processed/v1
uv run python main.py index
uv run python main.py query --text "AI ky 4 hoc gi?"
uv run pytest -q
```

Start Qdrant before indexing or set `QDRANT_URL` / `QDRANT_API_KEY`.
Do not point to an existing collection built with a *different* embedding pipeline:
use new collection names and rebuild both vector collections and BM25 indexes.

Embedding backends:

- `EMBEDDING_PROVIDER=api` (default): existing external ONNX-compatible embedding API.
  Ensure it returns the same vectors used by the indexed documents. Setting a model
  version string alone does **not** guarantee compatibility.
- `EMBEDDING_PROVIDER=sentence-transformers`: install with
  `uv sync --extra embedding-local`, then use the same model for indexing and
  querying. This provides `encode_document` / `encode_query` task-specific calls.
  It may download model weights and needs suitable RAM/VRAM.

The notebook's older raw-transformers mean-pooling method must not be mixed with
sentence-transformers or the external API's vectors. Regenerate collections
before comparing retrieval quality.

The baseline evaluation uses metadata-derived *proxy* relevance judgments,
not independent human annotations. Precision, recall, MRR and nDCG are diagnostic,
not a verified quality guarantee.
