#!/usr/bin/env python3
"""
Fixed-Size Chunker

Chunks text into fixed-size pieces with configurable overlap.
Fallback strategy that always works.

Usage:
    from tools.chunkers.fixed_chunker import FixedChunker
    chunker = FixedChunker(chunk_size=512, overlap=50)
    chunks = chunker.chunk(text)
"""

from typing import List, Dict


class FixedChunker:
    """Fixed-size chunking strategy."""

    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        """
        Initialize fixed chunker.

        Args:
            chunk_size: Chunk size in tokens (approximate)
            overlap: Overlap size in tokens
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation: words * 1.3)."""
        words = len(text.split())
        return int(words * 1.3)

    def tokens_to_chars(self, tokens: int, text: str) -> int:
        """Estimate character count for given token count."""
        total_tokens = self.estimate_tokens(text)
        chars_per_token = len(text) / max(total_tokens, 1)
        return int(tokens * chars_per_token)

    def chunk(self, text: str) -> List[Dict]:
        """
        Chunk text into fixed-size pieces with overlap.

        Args:
            text: Input text

        Returns:
            List of chunk dictionaries
        """
        if not text.strip():
            return []

        # Estimate character sizes
        chunk_chars = self.tokens_to_chars(self.chunk_size, text)
        overlap_chars = self.tokens_to_chars(self.overlap, text)
        stride = chunk_chars - overlap_chars

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_chars

            # Get chunk text
            chunk_text = text[start:end].strip()

            if chunk_text:
                chunks.append({
                    'text': chunk_text,
                    'start_char': start,
                    'end_char': end,
                    'estimated_tokens': self.estimate_tokens(chunk_text)
                })

            start += stride

            # Prevent infinite loop
            if stride <= 0:
                break

        return chunks


if __name__ == "__main__":
    # Test
    sample_text = " ".join([f"This is sentence number {i}." for i in range(1, 50)])

    chunker = FixedChunker(chunk_size=50, overlap=10)
    chunks = chunker.chunk(sample_text)

    print(f"Created {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks, 1):
        print(f"\nChunk {i}:")
        print(f"  Tokens: ~{chunk['estimated_tokens']}")
        print(f"  Text: {chunk['text'][:100]}...")
