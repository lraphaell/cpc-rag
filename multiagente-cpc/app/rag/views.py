"""RAG Retrieval endpoint — Flask version of retrieval_endpoint.py."""

import logging
import re
import secrets
import threading

from flask import Blueprint, jsonify, request

from app.rag.config import RETRIEVAL_API_KEY

logger = logging.getLogger(__name__)

rag = Blueprint("rag", __name__)

# Allowed Pinecone metadata filter keys
_ALLOWED_FILTER_KEYS = {"country", "team", "bandera", "fecha", "drive_file_id"}

# Regex for validating filter values (alphanumeric, hyphens, spaces, commas)
_VALID_FILTER_VALUE = re.compile(r"^[\w\s,\-\.]+$", re.UNICODE)

# Thread-safe lazy client initialization
_client = None
_client_lock = threading.Lock()
_client_error = None


def _get_client():
    global _client, _client_error
    if _client is None:
        if _client_error is not None:
            raise _client_error
        with _client_lock:
            if _client is None and _client_error is None:
                try:
                    from app.rag.pinecone_client import PineconeClient
                    _client = PineconeClient()
                except Exception as e:
                    _client_error = e
                    raise
    return _client


@rag.route("/health")
def health():
    """Keep-alive endpoint."""
    return jsonify({"status": "ok"})


@rag.route("/retrieve", methods=["POST"])
def retrieve():
    """
    Embed question with Gemini, query Pinecone, return top chunks.

    Requires header: X-API-Key: <RETRIEVAL_API_KEY>

    Body JSON:
        {"question": "...", "top_k": 99, "filters": {"country": "MLA"}}
        {"question": "...", "filters": {"fecha": ["2025-Q1", "2025-Q2"], "country": ["MLA", "MLB"]}}
    """
    # Auth check — always required, reject if not configured
    if not RETRIEVAL_API_KEY:
        logger.error("RETRIEVAL_API_KEY not configured — rejecting request")
        return jsonify({"detail": "Service not configured"}), 503

    api_key = request.headers.get("X-API-Key", "")
    if not api_key or not secrets.compare_digest(api_key, RETRIEVAL_API_KEY):
        return jsonify({"detail": "Unauthorized"}), 401

    # Parse body
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"detail": "Request body must be JSON"}), 400

    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"detail": "question must not be empty"}), 422
    if len(question) > 2000:
        return jsonify({"detail": "question too long (max 2000 chars)"}), 422

    top_k = data.get("top_k", 99)
    if not isinstance(top_k, int) or not 1 <= top_k <= 99:
        return jsonify({"detail": "top_k must be between 1 and 99"}), 422

    filters = data.get("filters")
    if filters is not None:
        if not isinstance(filters, dict):
            return jsonify({"detail": "filters must be a JSON object"}), 422
        invalid_keys = set(filters.keys()) - _ALLOWED_FILTER_KEYS
        if invalid_keys:
            return jsonify({"detail": f"Invalid filter keys: {invalid_keys}"}), 422
        # Validate filter values — accept str (single) or list[str] (multi-value → $in)
        for key, value in filters.items():
            if isinstance(value, list):
                if not value or not all(
                    isinstance(v, str) and _VALID_FILTER_VALUE.match(v) for v in value
                ):
                    return jsonify({"detail": f"Invalid filter list for '{key}'"}), 422
            elif not isinstance(value, str) or not _VALID_FILTER_VALUE.match(value):
                return jsonify({"detail": f"Invalid filter value for '{key}'"}), 422

    # Transform list filter values to Pinecone $in syntax (OR matching)
    pinecone_filters = {}
    if filters:
        pinecone_filters = {
            k: ({"$in": v} if isinstance(v, list) else v)
            for k, v in filters.items()
        }

    # Query
    try:
        client = _get_client()
        chunks = client.query(
            text=question,
            top_k=top_k,
            filters=pinecone_filters,
        )
        return jsonify({"chunks": chunks, "count": len(chunks)})
    except Exception as e:
        logger.error("Retrieval failed: %s: %s", type(e).__name__, e)
        return jsonify({"detail": "Internal retrieval error"}), 500
