#!/usr/bin/env python3
"""
Reusable Pinecone SDK wrapper.

Handles connection, upsert (with pre-computed Gemini embeddings),
delete by file, and query.

Usage:
    from tools.ingestion.pinecone_client import PineconeClient

    client = PineconeClient()
    client.upsert_vectors(vectors, namespace="genova-prod")
    client.delete_by_file("drive_file_id_abc", namespace="genova-prod")
"""

import sys
import time
from typing import List, Dict, Optional

from tools.common.config import PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_NAMESPACE


class PineconeClient:
    """Wrapper around Pinecone SDK for RAG ingestion operations."""

    def __init__(self, api_key=None, index_name=None, namespace=None):
        self.api_key = api_key or PINECONE_API_KEY
        self.index_name = index_name or PINECONE_INDEX_NAME
        self.default_namespace = namespace or PINECONE_NAMESPACE

        if not self.api_key:
            raise ValueError("PINECONE_API_KEY not set")

        from pinecone import Pinecone
        self.pc = Pinecone(api_key=self.api_key)
        self.index = self.pc.Index(self.index_name)

        # Lazy-loaded embedder for query operations
        self._embedder = None

    @property
    def embedder(self):
        """Lazy-load GeminiEmbedder for query operations."""
        if self._embedder is None:
            from tools.embedding.gemini_embedder import GeminiEmbedder
            self._embedder = GeminiEmbedder()
        return self._embedder

    def stats(self, namespace=None):
        """Get index stats, optionally filtered by namespace."""
        stats = self.index.describe_index_stats()
        if namespace:
            ns_stats = stats.get("namespaces", {}).get(namespace, {})
            return {"total_vector_count": ns_stats.get("vector_count", 0)}
        return stats

    def upsert_vectors(self, vectors: List[Dict], namespace: str = None,
                       batch_size: int = 100, delay_between_batches: float = 1.0):
        """
        Upsert pre-embedded vectors to Pinecone.

        Args:
            vectors: List of {"id": str, "values": [float], "metadata": dict}
            namespace: Pinecone namespace
            batch_size: Vectors per batch
            delay_between_batches: Seconds between batches

        Returns:
            int: Number of vectors upserted
        """
        ns = namespace or self.default_namespace
        total = len(vectors)
        upserted = 0
        max_retries = 5

        for i in range(0, total, batch_size):
            batch = vectors[i:i + batch_size]
            batch_num = i // batch_size + 1

            for attempt in range(max_retries):
                try:
                    self.index.upsert(vectors=batch, namespace=ns)
                    upserted += len(batch)

                    if i + batch_size < total:
                        time.sleep(delay_between_batches)
                    break

                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "Too Many" in err_str:
                        wait = delay_between_batches * (2 ** attempt)
                        print(f"    Rate limited batch {batch_num}, waiting {wait}s (attempt {attempt+1}/{max_retries})")
                        time.sleep(wait)
                    else:
                        print(f"  Error in batch {batch_num}: {e}", file=sys.stderr)
                        raise
            else:
                print(f"  Batch {batch_num} failed after {max_retries} retries", file=sys.stderr)
                raise Exception(f"Rate limit exceeded after {max_retries} retries on batch {batch_num}")

        return upserted

    def _upsert_records_legacy(self, records: List[Dict], namespace: str = None,
                               batch_size: int = 96, delay_between_batches: float = 5.0):
        """
        Legacy: Upsert using Pinecone inference API (auto-embeddings).
        Kept for rollback. Use upsert_vectors() for new code.
        """
        ns = namespace or self.default_namespace
        total = len(records)
        upserted = 0
        max_retries = 5

        for i in range(0, total, batch_size):
            batch = records[i:i + batch_size]
            batch_num = i // batch_size + 1

            for attempt in range(max_retries):
                try:
                    self.index.upsert_records(namespace=ns, records=batch)
                    upserted += len(batch)

                    if i + batch_size < total:
                        time.sleep(delay_between_batches)
                    break

                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "Too Many" in err_str:
                        wait = delay_between_batches * (2 ** attempt)
                        print(f"    Rate limited batch {batch_num}, waiting {wait}s (attempt {attempt+1}/{max_retries})")
                        time.sleep(wait)
                    else:
                        print(f"  Error in batch {batch_num}: {e}", file=sys.stderr)
                        raise
            else:
                print(f"  Batch {batch_num} failed after {max_retries} retries", file=sys.stderr)
                raise Exception(f"Rate limit exceeded after {max_retries} retries on batch {batch_num}")

        return upserted

    def delete_by_file(self, drive_file_id: str, namespace: str = None):
        """
        Delete all chunks belonging to a specific file.

        Args:
            drive_file_id: Google Drive file ID
            namespace: Pinecone namespace

        Returns:
            bool: True if successful
        """
        ns = namespace or self.default_namespace
        try:
            self.index.delete(
                filter={"drive_file_id": {"$eq": drive_file_id}},
                namespace=ns,
            )
            return True
        except Exception as e:
            print(f"  Warning: delete_by_file failed for {drive_file_id}: {e}", file=sys.stderr)
            return False

    def delete_by_ids(self, ids: List[str], namespace: str = None):
        """Delete chunks by explicit ID list."""
        ns = namespace or self.default_namespace
        for i in range(0, len(ids), 1000):
            batch = ids[i:i + 1000]
            self.index.delete(ids=batch, namespace=ns)

    def query(self, text: str, top_k: int = 5, namespace: str = None,
              filters: Dict = None) -> List[Dict]:
        """
        Query Pinecone using text (embedded via Gemini Embedding 2).

        Args:
            text: Query text
            top_k: Number of results
            namespace: Pinecone namespace
            filters: Metadata filter dict

        Returns:
            List of {id, score, text, metadata...}
        """
        ns = namespace or self.default_namespace

        # Generate query embedding via Gemini
        query_vector = self.embedder.embed_query(text)

        kwargs = {
            "namespace": ns,
            "vector": query_vector,
            "top_k": top_k,
            "include_metadata": True,
        }
        if filters:
            kwargs["filter"] = filters

        results = self.index.query(**kwargs)

        return [
            {
                "id": m.id,
                "score": m.score,
                **m.metadata,
            }
            for m in results.matches
        ]


def flatten_metadata(metadata: Dict) -> Dict:
    """
    Flatten nested metadata for Pinecone upsert.
    Converts lists to comma-separated strings since Pinecone
    metadata values must be primitives.
    """
    flat = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            flat[key] = value
        elif isinstance(value, list):
            flat[key] = ", ".join(str(item) for item in value)
        elif isinstance(value, dict):
            for nk, nv in value.items():
                flat[f"{key}.{nk}"] = nv if isinstance(nv, (str, int, float, bool)) else str(nv)
        elif value is None:
            continue
        else:
            flat[key] = str(value)
    return flat
