#!/usr/bin/env python3
"""
Genova RAG Retrieval Endpoint

Minimal FastAPI endpoint for n8n integration.
Accepts a question + optional filters, returns Pinecone chunks as JSON.
Synthesis is intentionally NOT done here — delegated to n8n's AI Agent node.

Deploy: Render.com
  Build:  pip install -r requirements-api.txt
  Start:  uvicorn tools.api.retrieval_endpoint:app --host 0.0.0.0 --port $PORT
"""

import os
import sys

# Ensure project root is on path (required when running from Render.com)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, field_validator
from typing import Optional, Annotated

from tools.ingestion.pinecone_client import PineconeClient

app = FastAPI(title="Genova RAG Retrieval", version="1.0")

# Shared secret loaded from env — set RETRIEVAL_API_KEY in Render dashboard
# and add the same value as X-API-Key header in n8n's HTTP Request node.
RETRIEVAL_API_KEY = os.getenv("RETRIEVAL_API_KEY", "")

# Initialize once at startup (cached for the lifetime of the process)
_client: Optional[PineconeClient] = None

# Allowed Pinecone metadata filter keys (prevents arbitrary key injection)
_ALLOWED_FILTER_KEYS = {"country", "team", "bandera", "fecha", "drive_file_id"}


def get_client() -> PineconeClient:
    global _client
    if _client is None:
        _client = PineconeClient()
    return _client


def _verify_api_key(x_api_key: str) -> None:
    """Raise 401 if the shared secret is configured and the header doesn't match."""
    if RETRIEVAL_API_KEY and x_api_key != RETRIEVAL_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Request / Response schemas ────────────────────────────────────────

class RetrieveRequest(BaseModel):
    question: str
    top_k: int = 8
    filters: Optional[dict] = None

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be empty")
        if len(v) > 2000:
            raise ValueError("question too long (max 2000 chars)")
        return v.strip()

    @field_validator("top_k")
    @classmethod
    def top_k_range(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError("top_k must be between 1 and 20")
        return v

    @field_validator("filters")
    @classmethod
    def filters_keys_allowed(cls, v: Optional[dict]) -> Optional[dict]:
        if v is None:
            return v
        invalid = set(v.keys()) - _ALLOWED_FILTER_KEYS
        if invalid:
            raise ValueError(f"Invalid filter keys: {invalid}. Allowed: {_ALLOWED_FILTER_KEYS}")
        return v


# ── Endpoints ─────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Keep-alive endpoint for UptimeRobot."""
    return {"status": "ok"}


@app.post("/retrieve")
def retrieve(
    req: RetrieveRequest,
    x_api_key: Annotated[str, Header()] = "",
):
    """
    Embed question with Gemini, query Pinecone, return top chunks.

    Requires header: X-API-Key: <RETRIEVAL_API_KEY>

    Filters accepted (all optional):
      {"country": "MLA", "team": "Optimus", "bandera": "Visa", "fecha": "2025-Q4"}
    """
    _verify_api_key(x_api_key)
    try:
        client = get_client()
        chunks = client.query(
            text=req.question,
            top_k=req.top_k,
            filters=req.filters or {},
        )
        return {"chunks": chunks, "count": len(chunks)}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal retrieval error")
