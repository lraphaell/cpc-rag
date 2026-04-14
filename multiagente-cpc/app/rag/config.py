"""Configuration — loads secrets from Fury SDK with os.getenv fallback."""

import logging
import os

logger = logging.getLogger(__name__)


def _get_secret(name: str, default: str = "") -> str:
    """Try Fury Secrets SDK first, fall back to env var."""
    try:
        from melitk.secrets import Secret  # noqa: F811
        value = Secret(name).get()
        if value:
            return value
    except ImportError:
        pass  # Expected when running outside Fury
    except Exception:
        logger.warning("Failed to load secret '%s' from Fury SDK, falling back to env var", name)
    return os.getenv(name, default)


# Pinecone
PINECONE_API_KEY = _get_secret("PINECONE_API_KEY")
PINECONE_INDEX_NAME = _get_secret("PINECONE_INDEX_NAME", "genova-v2")
PINECONE_NAMESPACE = _get_secret("PINECONE_NAMESPACE", "genova-prod")

# Gemini Embeddings
GEMINI_API_KEY = _get_secret("GEMINI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2-preview")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))

# Endpoint auth
RETRIEVAL_API_KEY = _get_secret("RETRIEVAL_API_KEY")
