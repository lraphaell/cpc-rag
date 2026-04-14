"""Tests for RAG retrieval endpoint."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask.testing import FlaskClient

import importlib

rag_views = importlib.import_module("app.rag.views")
rag_config = importlib.import_module("app.rag.config")
rag_embedder = importlib.import_module("app.rag.embedder")
rag_pinecone = importlib.import_module("app.rag.pinecone_client")

API_KEY = "test-secret-key"


@pytest.fixture(autouse=True)
def setup_auth(monkeypatch):
    """Configure API key auth for all tests."""
    monkeypatch.setattr(rag_views, "RETRIEVAL_API_KEY", API_KEY)


def _auth_headers():
    return {"X-API-Key": API_KEY}


def test_health(client: FlaskClient) -> None:
    """Test health endpoint returns ok."""
    response = client.get("/health")
    assert response.status_code == HTTPStatus.OK
    assert response.json == {"status": "ok"}


def test_retrieve_unconfigured_api_key(client: FlaskClient, monkeypatch) -> None:
    """Test retrieve returns 503 when API key not configured."""
    monkeypatch.setattr(rag_views, "RETRIEVAL_API_KEY", "")
    response = client.post("/retrieve", json={"question": "test"})
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_retrieve_no_api_key(client: FlaskClient) -> None:
    """Test retrieve rejects missing API key."""
    response = client.post("/retrieve", json={"question": "test"})
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_retrieve_wrong_api_key(client: FlaskClient) -> None:
    """Test retrieve rejects wrong API key."""
    response = client.post(
        "/retrieve",
        json={"question": "test"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_retrieve_empty_question(client: FlaskClient) -> None:
    """Test retrieve rejects empty question."""
    response = client.post(
        "/retrieve", json={"question": ""}, headers=_auth_headers()
    )
    assert response.status_code == 422


def test_retrieve_question_too_long(client: FlaskClient) -> None:
    """Test retrieve rejects question over 2000 chars."""
    response = client.post(
        "/retrieve", json={"question": "x" * 2001}, headers=_auth_headers()
    )
    assert response.status_code == 422


def test_retrieve_invalid_top_k(client: FlaskClient) -> None:
    """Test retrieve rejects top_k out of range."""
    response = client.post(
        "/retrieve",
        json={"question": "test", "top_k": 99},
        headers=_auth_headers(),
    )
    assert response.status_code == 422


def test_retrieve_invalid_filter_keys(client: FlaskClient) -> None:
    """Test retrieve rejects unknown filter keys."""
    response = client.post(
        "/retrieve",
        json={"question": "test", "filters": {"invalid_key": "val"}},
        headers=_auth_headers(),
    )
    assert response.status_code == 422


def test_retrieve_invalid_filter_values(client: FlaskClient) -> None:
    """Test retrieve rejects filter values with special characters."""
    response = client.post(
        "/retrieve",
        json={"question": "test", "filters": {"country": "MLA'; DROP TABLE--"}},
        headers=_auth_headers(),
    )
    assert response.status_code == 422


def test_retrieve_no_body(client: FlaskClient) -> None:
    """Test retrieve rejects request without JSON body."""
    response = client.post("/retrieve", headers=_auth_headers())
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_retrieve_success(client: FlaskClient, monkeypatch) -> None:
    """Test retrieve returns chunks on valid request."""
    mock_client = MagicMock()
    mock_client.query.return_value = [
        {"id": "chunk_1", "score": 0.9, "text": "test content"}
    ]
    monkeypatch.setattr(rag_views, "_get_client", lambda: mock_client)

    response = client.post(
        "/retrieve",
        json={"question": "test query", "top_k": 5},
        headers=_auth_headers(),
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json
    assert data["count"] == 1
    assert data["chunks"][0]["id"] == "chunk_1"


def test_retrieve_with_filters(client: FlaskClient, monkeypatch) -> None:
    """Test retrieve passes filters to client."""
    mock_client = MagicMock()
    mock_client.query.return_value = []
    monkeypatch.setattr(rag_views, "_get_client", lambda: mock_client)

    response = client.post(
        "/retrieve",
        json={
            "question": "reglas Visa",
            "filters": {"country": "MLA", "bandera": "Visa"},
        },
        headers=_auth_headers(),
    )

    assert response.status_code == HTTPStatus.OK
    mock_client.query.assert_called_once_with(
        text="reglas Visa",
        top_k=8,
        filters={"country": "MLA", "bandera": "Visa"},
    )


# ── Config tests ─────────────────────────────────────────────────────


def test_config_get_secret_fallback(monkeypatch) -> None:
    """Test _get_secret falls back to env var."""
    monkeypatch.setenv("TEST_SECRET_KEY", "from-env")
    result = rag_config._get_secret("TEST_SECRET_KEY", "default")
    assert result == "from-env"


def test_config_get_secret_default() -> None:
    """Test _get_secret returns default when env var missing."""
    result = rag_config._get_secret("NONEXISTENT_KEY_XYZ", "fallback")
    assert result == "fallback"


# ── Embedder tests ───────────────────────────────────────────────────


def test_embedder_requires_api_key(monkeypatch) -> None:
    """Test GeminiEmbedder raises without API key."""
    monkeypatch.setattr(rag_embedder, "GEMINI_API_KEY", "")
    with pytest.raises(ValueError, match="GEMINI_API_KEY not set"):
        rag_embedder.GeminiEmbedder()


def test_embedder_embed_query(monkeypatch) -> None:
    """Test embed_query calls Gemini API correctly."""
    monkeypatch.setattr(rag_embedder, "GEMINI_API_KEY", "fake-key")

    mock_genai = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.values = [0.1, 0.2, 0.3]
    mock_result = MagicMock()
    mock_result.embeddings = [mock_embedding]
    mock_genai.Client.return_value.models.embed_content.return_value = mock_result

    with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": mock_genai}):
        monkeypatch.setattr(rag_embedder, "GEMINI_API_KEY", "fake-key")
        embedder = rag_embedder.GeminiEmbedder()
        embedder.client = mock_genai.Client.return_value
        embedder.types = MagicMock()
        result = embedder.embed_query("test query")

    assert result == [0.1, 0.2, 0.3]


def test_embedder_empty_response(monkeypatch) -> None:
    """Test embed_query raises on empty embeddings response."""
    monkeypatch.setattr(rag_embedder, "GEMINI_API_KEY", "fake-key")

    mock_genai = MagicMock()
    mock_result = MagicMock()
    mock_result.embeddings = []
    mock_genai.Client.return_value.models.embed_content.return_value = mock_result

    with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": mock_genai}):
        embedder = rag_embedder.GeminiEmbedder()
        embedder.client = mock_genai.Client.return_value
        embedder.types = MagicMock()
        with pytest.raises(RuntimeError, match="empty embeddings"):
            embedder.embed_query("test")


# ── PineconeClient tests ────────────────────────────────────────────


def test_pinecone_client_requires_api_key(monkeypatch) -> None:
    """Test PineconeClient raises without API key."""
    monkeypatch.setattr(rag_pinecone, "PINECONE_API_KEY", "")
    with pytest.raises(ValueError, match="PINECONE_API_KEY not set"):
        rag_pinecone.PineconeClient()


def test_pinecone_client_query(monkeypatch) -> None:
    """Test PineconeClient.query delegates to index and embedder."""
    monkeypatch.setattr(rag_pinecone, "PINECONE_API_KEY", "fake-key")
    monkeypatch.setattr(rag_pinecone, "PINECONE_INDEX_NAME", "test-index")
    monkeypatch.setattr(rag_pinecone, "PINECONE_NAMESPACE", "test-ns")

    mock_pinecone_mod = MagicMock()
    mock_index = MagicMock()
    mock_pinecone_mod.Pinecone.return_value.Index.return_value = mock_index

    match = MagicMock()
    match.id = "chunk_1"
    match.score = 0.95
    match.metadata = {"text": "hello", "country": "MLA"}
    mock_index.query.return_value.matches = [match]

    with patch.dict("sys.modules", {"pinecone": mock_pinecone_mod}):
        client = rag_pinecone.PineconeClient()
        client.index = mock_index

        mock_embedder = MagicMock()
        mock_embedder.embed_query.return_value = [0.1, 0.2]
        client._embedder = mock_embedder

        results = client.query("test", top_k=3, filters={"country": "MLA"})

    assert len(results) == 1
    assert results[0]["id"] == "chunk_1"
    assert results[0]["country"] == "MLA"
    mock_embedder.embed_query.assert_called_once_with("test")
