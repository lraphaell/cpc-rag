# RAG Pipeline Status

**Last updated:** 2026-03-19

---

## Current State

| Component | Status | Details |
|-----------|--------|---------|
| Pipeline Stages 1-7 | OPERATIONAL | Full 7-stage pipeline functional |
| Pinecone (old) | `agentic-rag` | 836 vectors, multilingual-e5-large 1024d — ROLLBACK ONLY |
| Pinecone (new) | `genova-gemini-768` | Pending creation — Gemini Embedding 2, 768d |
| Embedding Model | Gemini Embedding 2 | `gemini-embedding-2-preview`, multimodal (text+image) |
| Cleaned JSONs | 151 files | All metadata_status: reviewed |
| Blocked downloads | 22 files | 403 errors, manual download needed |
| Streamlit Chat | LIVE | `app.py` with metadata filters |

## Embedding Migration (2026-03-19)

Migrated from Pinecone Inference API (auto-embeddings via `multilingual-e5-large`) to
pre-computed vectors via **Gemini Embedding 2**.

### Why
- Old: text-only embeddings, no visual content from PPTX/PDF/XLSX
- New: multimodal (text + images), unified vector space, #1 MTEB Multilingual benchmark
- Future: can embed slide images and PDF pages directly (Phase 4)

### What Changed
- `tools/embedding/gemini_embedder.py` — NEW: Gemini Embedding 2 wrapper
- `tools/ingestion/pinecone_client.py` — `upsert_vectors()` replaces `upsert_records()`
- `tools/ingestion/process_and_ingest.py` — embeds via Gemini before upsert
- `tools/query/rag_engine.py` — queries via Gemini embedding (not Pinecone inference)
- `tools/query/query_rag.py` — same
- `tools/common/config.py` — EMBEDDING_MODEL, EMBEDDING_DIMENSIONS constants
- `tools/ingestion/create_gemini_index.py` — NEW: creates Pinecone index for Gemini

### Pending
- [ ] Create Pinecone index `genova-gemini-768`
- [ ] Re-ingest 151 cleaned JSONs (~980 chunks, ~$0.06 cost)
- [ ] Verify queries against new index
- [ ] Switch `.env` to `PINECONE_INDEX_NAME=genova-gemini-768`
- [ ] Phase 4: multimodal embedding for PPTX slides and PDF pages

### Rollback
Set `PINECONE_INDEX_NAME=agentic-rag` in `.env`. Old index preserved for 2 weeks.

---

## Pipeline Commands

```bash
# Full pipeline:
PYTHONPATH=. python tools/fetch/fetch_dataset.py
PYTHONPATH=. python tools/state/detect_changes.py
PYTHONPATH=. python tools/fetch/download_files.py
PYTHONPATH=. python tools/cleanup/prepare_chunks.py
# Stage 5: Agent metadata extraction (conversational)
PYTHONPATH=. python tools/ingestion/process_and_ingest.py
PYTHONPATH=. python tools/reporting/generate_report.py

# Create new Pinecone index:
PYTHONPATH=. python tools/ingestion/create_gemini_index.py

# Query test:
PYTHONPATH=. python tools/query/query_rag.py --question "proyectos 2025 MLB"
```
