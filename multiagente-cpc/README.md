# multiagente-cpc

![technology Python](https://img.shields.io/badge/technology-python-blue.svg)

RAG retrieval endpoint for the Genova team's knowledge base.

## What it does

Receives a question via HTTP POST, converts it to a vector embedding (Gemini), searches Pinecone for relevant document chunks, and returns them as JSON. Designed to be called by n8n (Verdi Flows) as part of the Javo Slack chatbot.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/ping` | Health check (Fury) |
| `GET` | `/health` | Health check (custom) |
| `POST` | `/retrieve` | Query the RAG knowledge base |

### POST /retrieve

**Headers:**
- `Content-Type: application/json`
- `X-API-Key: <RETRIEVAL_API_KEY>`

**Body:**
```json
{
  "question": "Reglas de Visa en Argentina",
  "top_k": 8,
  "filters": {
    "country": "MLA",
    "bandera": "Visa"
  }
}
```

**Response:**
```json
{
  "chunks": [
    {
      "id": "abc_chunk_0",
      "score": 0.87,
      "text": "Las reglas de Visa...",
      "country": "MLA",
      "file_name": "Reglas Visa.pdf"
    }
  ],
  "count": 1
}
```

### Available filters

| Key | Values |
|-----|--------|
| `country` | MLA, MLB, MLM, MLU, MLC, MCO, Corp |
| `team` | Genova, Optimus, Bari, etc. |
| `bandera` | Visa, Mastercard, American Express, Elo, Cabal, etc. |
| `fecha` | YYYY-QN format (e.g. 2025-Q4) |

## Architecture

```
n8n (Verdi Flows)
  |
  |  POST /retrieve
  v
multiagente-cpc (this app)
  |
  |-- Gemini API --> generates query embedding
  |-- Pinecone  --> vector similarity search
  |
  v
JSON response with ranked chunks
```

## Secrets

Configure in Fury Secrets:

| Secret | Purpose |
|--------|---------|
| `PINECONE_API_KEY` | Pinecone authentication |
| `GEMINI_API_KEY` | Google Gemini embeddings |
| `RETRIEVAL_API_KEY` | Endpoint authentication (sent by n8n) |

## Development

```bash
# Clone
fury get multiagente-cpc

# Install dependencies
poetry install

# Run locally
poetry shell
python -m app

# Run tests
poetry run pytest

# Or via Fury
fury test
```

## Project structure

```
app/
  ping/views.py          # /ping health check
  dummy/views.py         # Example endpoint (Flask-RESTX)
  rag/
    config.py            # Secrets loader (Fury SDK + env fallback)
    embedder.py          # Gemini Embedding 2 wrapper
    pinecone_client.py   # Pinecone query client
    views.py             # /retrieve and /health endpoints
tests/
  test_ping.py
  test_rag.py
  test_metrics.py
```
