#!/usr/bin/env python3
"""
Semantic Chunker

Chunks text based on semantic coherence using sentence boundaries.
Best for narrative text (PDFs, Word docs, articles).

Usage:
    from tools.chunkers.semantic_chunker import SemanticChunker
    chunker = SemanticChunker(target_size=500, overlap=50)
    chunks = chunker.chunk(text)
"""

from typing import List, Dict
import re


class SemanticChunker:
    """Semantic chunking strategy using sentence boundaries."""

    def __init__(self, target_size: int = 512, overlap: int = 50):
        """
        Initialize semantic chunker.

        Args:
            target_size: Target chunk size in tokens (approximate)
            overlap: Overlap size in tokens
        """
        self.target_size = target_size
        self.overlap = overlap

    def split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        # Simple sentence splitting (can be improved with spaCy/NLTK)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation: words * 1.3)."""
        words = len(text.split())
        return int(words * 1.3)

    def chunk(self, text: str) -> List[Dict]:
        """
        Chunk text using semantic boundaries.

        Args:
            text: Input text

        Returns:
            List of chunk dictionaries with 'text' and metadata
        """
        sentences = self.split_into_sentences(text)
        chunks = []
        current_chunk = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = self.estimate_tokens(sentence)

            # If adding this sentence exceeds target, save current chunk
            if current_tokens + sentence_tokens > self.target_size and current_chunk:
                chunk_text = ' '.join(current_chunk)
                chunks.append({
                    'text': chunk_text,
                    'token_count': current_tokens,
                    'sentence_count': len(current_chunk)
                })

                # Keep overlap sentences
                overlap_tokens = 0
                overlap_sentences = []
                for sent in reversed(current_chunk):
                    sent_tokens = self.estimate_tokens(sent)
                    if overlap_tokens + sent_tokens <= self.overlap:
                        overlap_sentences.insert(0, sent)
                        overlap_tokens += sent_tokens
                    else:
                        break

                current_chunk = overlap_sentences
                current_tokens = overlap_tokens

            # Add sentence to current chunk
            current_chunk.append(sentence)
            current_tokens += sentence_tokens

        # Add final chunk
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            chunks.append({
                'text': chunk_text,
                'token_count': current_tokens,
                'sentence_count': len(current_chunk)
            })

        return chunks


if __name__ == "__main__":
    # Test
    sample_text = """
    This is the first sentence. This is the second sentence.
    This is the third sentence. This is the fourth sentence.
    This is the fifth sentence. This is the sixth sentence.
    """

    chunker = SemanticChunker(target_size=20, overlap=5)
    chunks = chunker.chunk(sample_text)

    print(f"Created {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks, 1):
        print(f"\nChunk {i}:")
        print(f"  Tokens: {chunk['token_count']}")
        print(f"  Text: {chunk['text'][:100]}...")
