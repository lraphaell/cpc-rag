"""Pinecone client — query only (for retrieval endpoint)."""

import logging
import threading
from typing import Dict, List, Optional

from app.rag.config import PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_NAMESPACE

logger = logging.getLogger(__name__)

# Query timeout in seconds
_QUERY_TIMEOUT = 10


class PineconeClient:
    """Wrapper around Pinecone SDK for RAG query operations."""

    def __init__(self):
        if not PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY not set")

        from pinecone import Pinecone

        self.pc = Pinecone(api_key=PINECONE_API_KEY)
        self.index = self.pc.Index(PINECONE_INDEX_NAME)
        self._embedder = None
        self._embedder_lock = threading.Lock()
        self._embedder_error = None

    @property
    def embedder(self):
        if self._embedder is None:
            if self._embedder_error is not None:
                raise self._embedder_error
            with self._embedder_lock:
                if self._embedder is None and self._embedder_error is None:
                    try:
                        from app.rag.embedder import GeminiEmbedder
                        self._embedder = GeminiEmbedder()
                    except Exception as e:
                        self._embedder_error = e
                        raise
        return self._embedder

    def query(self, text: str, top_k: int = 5,
              filters: Optional[Dict] = None) -> List[Dict]:
        """
        Embed question via Gemini, query Pinecone, return top chunks.

        Returns list of {id, score, text, metadata...}
        """
        query_vector = self.embedder.embed_query(text)

        kwargs = {
            "namespace": PINECONE_NAMESPACE,
            "vector": query_vector,
            "top_k": top_k,
            "include_metadata": True,
            "timeout": _QUERY_TIMEOUT,
        }
        if filters:
            kwargs["filter"] = filters

        results = self.index.query(**kwargs)

        return [
            {**m.metadata, "id": m.id, "score": m.score}
            for m in results.matches
        ]
