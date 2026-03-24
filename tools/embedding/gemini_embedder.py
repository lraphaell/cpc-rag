#!/usr/bin/env python3
"""
Gemini Embedding 2 wrapper for the RAG pipeline.

Generates embeddings via Google's gemini-embedding-2-preview model,
supporting text and image modalities in a unified 768-dim vector space.

Usage:
    from tools.embedding.gemini_embedder import GeminiEmbedder

    embedder = GeminiEmbedder()

    # Document embedding (batch)
    vectors = embedder.embed_texts(["chunk 1", "chunk 2"])

    # Query embedding
    query_vec = embedder.embed_query("search question")

    # Image embedding
    with open("slide.png", "rb") as f:
        img_vec = embedder.embed_image(f.read())
"""

import sys
import time
from typing import List, Optional

from tools.common.config import GEMINI_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS, EMBEDDING_BATCH_SIZE


class GeminiEmbedder:
    """Wrapper around Gemini Embedding 2 API with batch support and rate limiting."""

    def __init__(self, api_key: str = None, model: str = None, dimensions: int = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model = model or EMBEDDING_MODEL
        self.dimensions = dimensions or EMBEDDING_DIMENSIONS
        self.batch_size = EMBEDDING_BATCH_SIZE

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set. Add it to .env")

        from google import genai
        self.client = genai.Client(api_key=self.api_key)
        self._types = None  # Lazy import for types

    @property
    def types(self):
        if self._types is None:
            from google.genai import types
            self._types = types
        return self._types

    def embed_texts(self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
        """
        Embed a list of text strings in batches.

        Args:
            texts: List of text chunks to embed
            task_type: RETRIEVAL_DOCUMENT (for indexing) or RETRIEVAL_QUERY (for search)

        Returns:
            List of embedding vectors (each is a list of floats)
        """
        all_vectors = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            vectors = self._embed_with_retry(
                contents=batch,
                task_type=task_type,
            )
            all_vectors.extend(vectors)

            # Rate limit protection between batches
            if i + self.batch_size < len(texts):
                time.sleep(1.5)

        return all_vectors

    def embed_query(self, text: str) -> List[float]:
        """
        Embed a single query string.

        Args:
            text: The search query

        Returns:
            Embedding vector (list of floats)
        """
        vectors = self._embed_with_retry(
            contents=[text],
            task_type="RETRIEVAL_QUERY",
        )
        return vectors[0]

    def embed_image(self, image_bytes: bytes, mime_type: str = "image/png",
                    task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
        """
        Embed a single image.

        Args:
            image_bytes: Raw image bytes (PNG or JPEG)
            mime_type: Image MIME type
            task_type: Embedding task type

        Returns:
            Embedding vector (list of floats)
        """
        part = self.types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        vectors = self._embed_with_retry(
            contents=[part],
            task_type=task_type,
        )
        return vectors[0]

    def embed_images(self, images: List[dict], task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
        """
        Embed multiple images in sub-batches of 6 (API limit).

        Args:
            images: List of {"data": bytes, "mime_type": str}
            task_type: Embedding task type

        Returns:
            List of embedding vectors
        """
        all_vectors = []
        # Gemini allows max 6 images per request
        sub_batch_size = 6

        for i in range(0, len(images), sub_batch_size):
            batch = images[i:i + sub_batch_size]
            parts = [
                self.types.Part.from_bytes(data=img["data"], mime_type=img.get("mime_type", "image/png"))
                for img in batch
            ]
            vectors = self._embed_with_retry(
                contents=parts,
                task_type=task_type,
            )
            all_vectors.extend(vectors)

            if i + sub_batch_size < len(images):
                time.sleep(2)

        return all_vectors

    def _embed_with_retry(self, contents, task_type: str, max_retries: int = 8) -> List[List[float]]:
        """
        Call embed_content API with exponential backoff on rate limits.

        Args:
            contents: Text strings or Part objects to embed
            task_type: Embedding task type
            max_retries: Maximum retry attempts

        Returns:
            List of embedding vectors
        """
        config = self.types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self.dimensions,
        )

        for attempt in range(max_retries):
            try:
                result = self.client.models.embed_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                return [emb.values for emb in result.embeddings]

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "rate" in err_str.lower():
                    wait = min(2 ** attempt + 1, 60)  # Cap at 60s
                    print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                else:
                    print(f"  Embedding error: {e}", file=sys.stderr)
                    raise

        raise Exception(f"Embedding failed after {max_retries} retries (rate limited)")
