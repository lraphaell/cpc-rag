#!/usr/bin/env python3
"""
Structural Chunker

Chunks text based on document structure:
- Section-based (documents with headings)
- Slide-level (presentations)
- Row-based (spreadsheets)

Usage:
    from tools.chunkers.structural_chunker import StructuralChunker
    chunker = StructuralChunker()
    chunks = chunker.chunk(text, parsed_data)
"""

from typing import List, Dict, Any
import re


class StructuralChunker:
    """Structural chunking strategy."""

    def __init__(self):
        """Initialize structural chunker."""
        pass

    def chunk_by_sections(self, text: str) -> List[Dict]:
        """Chunk by sections (markdown headings or slide separators)."""
        # Look for section markers (=== or ###)
        sections = re.split(r'\n(?:===|###)\s*(.+?)\s*(?:===|###)\n', text)

        chunks = []
        current_section = ""
        current_title = None

        for i, part in enumerate(sections):
            if i % 2 == 0:
                # This is content
                current_section = part.strip()
            else:
                # This is a title
                if current_section:
                    chunks.append({
                        'text': current_section,
                        'section_title': current_title,
                        'type': 'section'
                    })
                current_title = part.strip()

        # Add final section
        if current_section:
            chunks.append({
                'text': current_section,
                'section_title': current_title,
                'type': 'section'
            })

        return chunks if chunks else self.chunk_by_paragraphs(text)

    def chunk_by_paragraphs(self, text: str) -> List[Dict]:
        """Fallback: chunk by paragraphs."""
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

        return [{
            'text': para,
            'type': 'paragraph'
        } for para in paragraphs]

    def chunk(self, text: str, metadata: Dict[str, Any] = None) -> List[Dict]:
        """
        Chunk text using structural boundaries.

        Args:
            text: Input text
            metadata: Optional metadata from parser (e.g., slide_count, sheet_names)

        Returns:
            List of chunk dictionaries
        """
        # Try to detect structure
        if '===' in text or '###' in text:
            return self.chunk_by_sections(text)
        else:
            return self.chunk_by_paragraphs(text)


if __name__ == "__main__":
    # Test
    sample_text = """
=== Introduction ===
This is the introduction section.
It has multiple sentences.

=== Methods ===
This is the methods section.
It describes the methodology.

=== Results ===
This is the results section.
It shows the findings.
    """

    chunker = StructuralChunker()
    chunks = chunker.chunk(sample_text)

    print(f"Created {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks, 1):
        print(f"\nChunk {i}:")
        print(f"  Type: {chunk.get('type')}")
        print(f"  Section: {chunk.get('section_title', 'N/A')}")
        print(f"  Text: {chunk['text'][:100]}...")
