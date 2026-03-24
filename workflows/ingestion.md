# Workflow: RAG Ingestion

## Objetivo
Processar arquivos (parse → chunk → embed → upsert) e ingerir no Pinecone de forma incremental.

## Tools
- `tools/ingestion/process_and_ingest.py` — Orquestrador principal
- `tools/ingestion/pinecone_client.py` — Cliente Pinecone reutilizável
- `tools/embedding/gemini_embedder.py` — Wrapper Gemini Embedding 2
- `tools/ingestion/create_gemini_index.py` — Cria index Pinecone para Gemini
- `tools/processing/parsers/` — Parsers por tipo de arquivo
- `tools/processing/chunkers/` — Estratégias de chunking

## Input
- `.tmp/change_manifest.json` (do detect_changes.py)
- Arquivos em `.tmp/downloads/` (do download_files.py)

## Output
- `.tmp/ingestion_log.json` com resultados
- Chunks no Pinecone (namespace `genova-prod`)
- `.tmp/state.json` atualizado per-file

## Embedding Model
- **Modelo**: `gemini-embedding-2-preview` (Gemini Embedding 2)
- **Dimensões**: 768 (Matryoshka — configurável de 128 a 3072)
- **Task types**: `RETRIEVAL_DOCUMENT` (ingestion), `RETRIEVAL_QUERY` (query)
- **Modalidades**: texto, imagens, vídeo, áudio, PDFs
- **Custo**: $0.20/M tokens (standard), $0.10/M tokens (batch API)
- **Wrapper**: `tools/embedding/gemini_embedder.py`

## Fluxo por Arquivo

### Para `add` (novo):
1. Parse documento (seleciona parser por extensão)
2. Chunk texto (semantic chunker, fallback: basic split)
3. Build records com metadata (filterable + technical)
4. Gerar embeddings via Gemini Embedding 2 (`embed_texts()`)
5. Upsert vectors pré-computados no Pinecone (`upsert_vectors()`)
6. Update state.json

### Para `update` (modificado):
1. Delete chunks antigos: `index.delete(filter={"drive_file_id": file_id})`
2. Mesmo fluxo que `add`

### Para `delete` (removido):
1. Delete chunks: `index.delete(filter={"drive_file_id": file_id})`
2. Remove do state.json

## Metadata por Chunk

### Campos Filtráveis (extraídos pelo agente por chunk)
- `team`, `country`, `bandera`, `fecha`

### Campos Técnicos (auto-populados)
- `drive_file_id`, `file_name`, `file_type`
- `chunk_index`, `total_chunks`
- `source_url`, `modified_time`, `ingested_at`
- `section_title`, `page_number`, `sheet_name`
- `chunking_method`

**Nota**: Com embeddings manuais (não auto-embed), o campo `text` é armazenado
explicitamente no metadata para aparecer nos resultados de query.

## Pinecone SDK
Usa `index.upsert(vectors=[...])` com vectors pré-computados pelo Gemini.
Index: `genova-gemini-768` (768 dims, cosine, serverless).

**Sem MCP proxy** — conexão direta via pinecone-client SDK.

## Comando
```bash
# Criar index (primeira vez):
PYTHONPATH=. python tools/ingestion/create_gemini_index.py

# Ingerir:
PYTHONPATH=. python tools/ingestion/process_and_ingest.py
```

## Rate Limiting
- Embedding batch size: 100 textos por chamada API
- Upsert batch size: 100 vectors
- Delay entre batches: 0.5s (embedding), 1s (upsert)
- Exponential backoff em 429 errors

## Migração (de multilingual-e5-large para Gemini Embedding 2)
- Index antigo: `agentic-rag` (1024 dims, inference API) — mantido como rollback
- Index novo: `genova-gemini-768` (768 dims, manual vectors)
- Espaços vetoriais são **incompatíveis** — re-embed obrigatório
- Para rollback: reverter `PINECONE_INDEX_NAME=agentic-rag` no `.env`
