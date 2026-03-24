#!/usr/bin/env python3
"""
Data Cleanup for RAG Agent — Centralized Configuration

All project-wide constants, IDs, and environment variables.
Loaded by every tool in the project.

Pattern ported from Mandoo project (tools/common/config.py).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Project paths ─────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TMP_DIR = PROJECT_ROOT / ".tmp"
DOWNLOADS_DIR = TMP_DIR / "downloads"
LOGS_DIR = TMP_DIR / "logs"
STATE_FILE = TMP_DIR / "state.json"

# Load .env from project root
load_dotenv(PROJECT_ROOT / ".env")

# ── Google API ────────────────────────────────────────────────────────
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH", str(PROJECT_ROOT / "credentials.json")
)
GOOGLE_TOKEN_PATH = os.getenv(
    "GOOGLE_TOKEN_PATH", str(PROJECT_ROOT / "token.json")
)

# ── Dataset Source (Google Sheets index) ──────────────────────────────
DATASET_SHEET_ID = os.getenv(
    "DATASET_SHEET_ID", "1gSMuR9YLn6ZfmUGJDODL0bz7jXwpQWqpT0xABa1i2Kc"
)
DATASET_GID = os.getenv("DATASET_GID", "0")

# ── Pinecone Vector Database ─────────────────────────────────────────
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT", "")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "genova-v2")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "genova-prod")

# ── Embedding Configuration ──────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2-preview")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))

# ── Processing Defaults ──────────────────────────────────────────────
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "10"))
CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "50"))
MAX_CHUNK_SIZE_TOKENS = int(os.getenv("MAX_CHUNK_SIZE_TOKENS", "512"))

# ── Logging ──────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", str(LOGS_DIR / "pipeline.log"))

# ── Optional APIs ────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Ensure temp directories exist ────────────────────────────────────
for d in [TMP_DIR, DOWNLOADS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)
