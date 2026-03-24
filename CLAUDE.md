# Agent Instructions

You're working inside the **WAT framework** (Workflows, Agents, Tools). This architecture separates concerns so that probabilistic AI handles reasoning while deterministic code handles execution. That separation is what makes this system reliable.

## The WAT Architecture

**Layer 1: Workflows (The Instructions)**
- Markdown SOPs stored in `workflows/`
- Each workflow defines the objective, required inputs, which tools to use, expected outputs, and how to handle edge cases
- Written in plain language, the same way you'd brief someone on your team

**Layer 2: Agents (The Decision-Maker)**
- This is your role. You're responsible for intelligent coordination.
- Read the relevant workflow, run tools in the correct sequence, handle failures gracefully, and ask clarifying questions when needed
- You connect intent to execution without trying to do everything yourself
- Example: If you need to pull data from a website, don't attempt it directly. Read `workflows/scrape_website.md`, figure out the required inputs, then execute `tools/scrape_single_site.py`

**Layer 3: Tools (The Execution)**
- Python scripts in `tools/` that do the actual work
- API calls, data transformations, file operations, database queries
- Credentials and API keys are stored in `.env`
- These scripts are consistent, testable, and fast

**Why this matters:** When AI tries to handle every step directly, accuracy drops fast. If each step is 90% accurate, you're down to 59% success after just five steps. By offloading execution to deterministic scripts, you stay focused on orchestration and decision-making where you excel.

## How to Operate

**1. Look for existing tools first**
Before building anything new, check `tools/` based on what your workflow requires. Only create new scripts when nothing exists for that task.

**2. Learn and adapt when things fail**
When you hit an error:
- Read the full error message and trace
- Fix the script and retest (if it uses paid API calls or credits, check with me before running again)
- Document what you learned in the workflow (rate limits, timing quirks, unexpected behavior)
- Example: You get rate-limited on an API, so you dig into the docs, discover a batch endpoint, refactor the tool to use it, verify it works, then update the workflow so this never happens again

**3. Keep workflows current**
Workflows should evolve as you learn. When you find better methods, discover constraints, or encounter recurring issues, update the workflow. That said, don't create or overwrite workflows without asking unless I explicitly tell you to. These are your instructions and need to be preserved and refined, not tossed after one use.

## The Self-Improvement Loop

Every failure is a chance to make the system stronger:
1. Identify what broke
2. Fix the tool
3. Verify the fix works
4. Update the workflow with the new approach
5. Move on with a more robust system

This loop is how the framework improves over time.

## Project Purpose

This agent specializes in **RAG (Retrieval-Augmented Generation) ingestion**: it takes a dataset of documents (listed in a Google Sheets index), processes them, and upserts vectorized chunks into Pinecone for semantic search and retrieval.

Key characteristics:
- **Living dataset**: Files are constantly updated by other people. Weekly execution detects changes and re-processes only what changed.
- **Incremental updates**: Uses `.tmp/state.json` to track file versions. Changed files have old chunks deleted before re-ingestion.
- **Pinecone**: Vector DB via direct SDK (no MCP proxy). Index: `genova-gemini-768`, namespace: `genova-prod`.
- **Embeddings**: Gemini Embedding 2 (`gemini-embedding-2-preview`), 768 dims, pre-computed vectors (not auto-embed). Wrapper: `tools/embedding/gemini_embedder.py`.
- **Google Auth**: Follows Mandoo pattern — gcloud CLI first, token.json fallback (see `tools/common/google_auth.py`).
- **Dataset source**: Google Sheets `1gSMuR9YLn6ZfmUGJDODL0bz7jXwpQWqpT0xABa1i2Kc` — a list with file metadata and Google Drive links.

## Pipeline Flow

```
Stage 1: fetch_dataset.py        → Read Sheets index, expand folders, get file links
Stage 2: detect_changes.py       → Compare against .tmp/state.json
Stage 3: download_files.py       → Download only changed/new files from Drive
Stage 4: prepare_chunks.py       → Parse → Chunk → Intermediate JSONs (.tmp/cleaned/)
Stage 5: AGENT metadata extract  → Analyze each chunk, fill team/country/bandera/fecha
Stage 6: process_and_ingest.py   → Read reviewed JSONs → Embed via Gemini → Upsert to Pinecone
Stage 7: generate_report.py      → Summary to Google Sheets
```

**Key**: Stages 1-4 and 6-7 are deterministic scripts. Stage 5 is agent-driven (probabilistic) —
the agent reads each chunk's text and extracts filterable metadata per-chunk, not per-file.
See `workflows/metadata_extraction.md` for the extraction rules.

## File Structure

**What goes where:**
- **Deliverables**: Final outputs go to cloud services (Google Sheets, Slides, etc.) where I can access them directly
- **Intermediates**: Temporary processing files that can be regenerated

**Directory layout:**
```
.tmp/                          # Temporary files. Regenerated as needed.
  state.json                   # Persistent state for change detection (DO NOT delete)
  downloads/                   # Downloaded files
  logs/                        # Run logs
tools/
  common/                      # Shared infrastructure
    config.py                  # Centralized configuration (env vars, constants, paths)
    google_auth.py             # Google auth (gcloud CLI + token.json dual method)
  fetch/                       # Data acquisition
    fetch_dataset.py           # Read Google Sheets dataset index + expand folders
    download_files.py          # Download files from Google Drive
  cleanup/                     # Data Cleanup (intermediate stage)
    prepare_chunks.py          # Parse → chunk → intermediate JSONs (.tmp/cleaned/)
    fix_fecha_format.py        # Fix fecha values (bare years → YYYY-QN lists)
    fix_duplicate_chunks.py    # Remove duplicate chunks within files
    fix_long_chunks.py         # Re-chunk oversized chunks (>5000 chars)
    fix_default_metadata.py    # Enrich default metadata from content keywords
    remove_tabular_chunks.py   # Remove raw tabular data from Pinecone
  processing/                  # Document processing
    parsers/                   # File-type specific parsers (pdf, office, spreadsheet, text)
    chunkers/                  # Chunking strategies (semantic, structural, fixed)
  embedding/                   # Embedding generation
    gemini_embedder.py         # Gemini Embedding 2 wrapper (text + image)
  ingestion/                   # Pinecone operations
    pinecone_client.py         # Reusable Pinecone SDK wrapper
    process_and_ingest.py      # Read cleaned JSONs → embed → upsert to Pinecone
    create_gemini_index.py     # Create Pinecone index for Gemini vectors
  state/                       # Change detection
    detect_changes.py          # Compare files against state.json
    update_state.py            # Persist state after successful run
  reporting/                   # Pipeline reporting
    generate_report.py         # Summary to Google Sheets
    validate_cleaned.py        # 13-check validation of cleaned JSONs
    generate_validation_report.py  # Validation report (Google Sheets + CSV)
    generate_final_check_report.py # Cross-reference: Dataset vs Cleaned vs Pinecone
  query/                       # RAG retrieval (for testing/querying)
    rag_engine.py              # Retrieve + synthesize (Gemini primary, Claude fallback)
    query_rag.py               # CLI query tool
    query_builder.py           # Transforms user question + filters into Pinecone query
workflows/                     # Markdown SOPs
  rag_pipeline.md              # Master workflow (7 stages)
  dataset_fetch.md             # How to read the Sheets index
  change_detection.md          # How incremental updates work
  metadata_extraction.md       # Agent-driven metadata extraction per chunk
  rag_strategy_analysis.md     # Strategy analysis workflow
  ingestion.md                 # Ingestion workflow (direct Pinecone)
.env                           # API keys and environment variables (NEVER store secrets elsewhere)
credentials.json, token.json   # Google OAuth (gitignored)
```

**Core principle:** Local files are just for processing. Anything I need to see or use lives in cloud services. Everything in `.tmp/` is disposable **except `state.json`** which tracks file versions for incremental updates.

## Sub-Agents

- **`rag-strategy-analyzer`** (`.claude/agents/rag-strategy-analyzer.md`): Analyzes each document and recommends chunking strategy, metadata extraction, and cleanup steps. Uses Claude Sonnet.
- **`quality-reviewer`** (`.claude/agents/quality-reviewer.md`): Reviews the entire codebase for bugs, inconsistencies, code duplication, and production readiness. Read-only — produces findings report without modifying files. Uses Claude Sonnet.
- **`pipeline-validator`** (`.claude/agents/pipeline-validator.md`): Validates end-to-end data integrity: Dataset → cleaned JSONs → state.json → Pinecone. Runs validation scripts, detects discrepancies, and suggests fix commands. Uses Claude Sonnet.

## Pinecone Metadata

Metadata is extracted **per chunk** (not per file), because a single document may reference multiple countries, card brands, and time periods.

Each chunk carries:
- **Filterable fields** (extracted by agent from chunk content):
  - `country`: MLA, MLB, MLM, MLU, MLC, MCO, Corp (default: Corp)
  - `team`: Genova, Relacionamiento con las banderas, Negocio cross, Bari, Mejora Continua y Planning, Scheme enablers, Optimus, X Countries (default: Genova)
  - `bandera`: Visa, Mastercard, American Express, Cabal, Elo, Hipercard, Carnet, Naranja, Otra (default: Otra)
  - `fecha`: 2025-Q1, 2026-Q2, etc. (formato YYYY-QN)
- **Technical fields** (auto-populated): `drive_file_id`, `file_name`, `file_type`, `chunk_index`, `total_chunks`, `source_url`, `modified_time`, `ingested_at`, `section_title`, `page_number`, `sheet_name`, `chunking_method`

The `drive_file_id` field is the primary key for incremental updates (delete old chunks by this filter before re-ingesting).

## Bottom Line

You sit between what I want (workflows) and what actually gets done (tools). Your job is to read instructions, make smart decisions, call the right tools, recover from errors, and keep improving the system as you go.

Stay pragmatic. Stay reliable. Keep learning.
