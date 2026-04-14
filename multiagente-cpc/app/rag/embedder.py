"""Gemini Embedding 2 wrapper — query embedding only."""

import time
from typing import List

from app.rag.config import GEMINI_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS

# Max total retry time: ~34s (3 + 5 + 9 + 17 = 34s worst case)
_MAX_RETRIES = 4
_MAX_BACKOFF = 17


class GeminiEmbedder:
    """Generates query embeddings via Gemini Embedding 2."""

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not set")

        from google import genai
        from google.genai import types

        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.types = types

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string with retry on rate limit.

        Retries up to 4 times with capped backoff (~34s max total).
        Backoff: 3s, 5s, 9s, 17s (2^attempt + 1, attempt starts at 1).
        """
        config = self.types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBEDDING_DIMENSIONS,
        )

        last_error = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result = self.client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=[text],
                    config=config,
                )
                if not result.embeddings:
                    raise RuntimeError("Gemini API returned empty embeddings list")
                return result.embeddings[0].values
            except (RuntimeError, ValueError):
                raise
            except Exception as e:
                last_error = e
                is_retryable = (
                    isinstance(e, (ConnectionError, TimeoutError))
                    or "429" in str(getattr(e, "code", ""))
                    or "RESOURCE_EXHAUSTED" in str(getattr(e, "code", ""))
                )
                if is_retryable and attempt < _MAX_RETRIES:
                    time.sleep(min(2 ** attempt + 1, _MAX_BACKOFF))
                elif is_retryable:
                    break  # Last attempt failed, skip useless sleep
                else:
                    raise

        raise RuntimeError(
            f"Embedding failed after {_MAX_RETRIES} retries: "
            f"{type(last_error).__name__}: {last_error}"
        )
