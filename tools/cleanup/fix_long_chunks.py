#!/usr/bin/env python3
"""
Re-chunk chunks that exceed the max character threshold.

Splits long chunks using SemanticChunker while preserving metadata.
Updates chunk_index and total_chunks after splitting.

Usage:
    PYTHONPATH=. python tools/cleanup/fix_long_chunks.py
    PYTHONPATH=. python tools/cleanup/fix_long_chunks.py --dry-run
    PYTHONPATH=. python tools/cleanup/fix_long_chunks.py --max-chars 4000
"""

import json
import sys
import argparse
from pathlib import Path

from tools.common.config import TMP_DIR
from tools.processing.chunkers.semantic_chunker import SemanticChunker

CLEANED_DIR = TMP_DIR / "cleaned"
DEFAULT_MAX_CHARS = 5000


def split_by_chars(text, max_chars, overlap_chars=200):
    """Fallback: split text by character count with overlap at space boundaries."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end >= len(text):
            chunks.append(text[start:])
            break
        # Try to break at a space
        space_pos = text.rfind(" ", start + max_chars - 500, end)
        if space_pos > start:
            end = space_pos
        chunks.append(text[start:end])
        start = end - overlap_chars
    return chunks


def split_long_chunk(chunk, chunker, max_chars):
    """Split a single long chunk into smaller chunks, preserving metadata."""
    text = chunk.get("text", "")
    metadata = chunk.get("metadata", {})

    sub_chunks = chunker.chunk(text)

    # If semantic chunker couldn't split (tabular data), use char-based split
    if len(sub_chunks) == 1 and len(sub_chunks[0]["text"]) > max_chars:
        text_parts = split_by_chars(text, max_chars)
        sub_chunks = [{"text": t} for t in text_parts]

    result = []
    for sc in sub_chunks:
        result.append({
            "chunk_index": 0,  # will be reindexed later
            "text": sc["text"],
            "metadata": dict(metadata),  # copy metadata to each sub-chunk
        })
    return result


def fix_long_chunks(filepath, max_chars, chunker, dry_run=False):
    """Fix long chunks in a single file. Returns (split_count, new_total)."""
    with open(filepath) as f:
        data = json.load(f)

    chunks = data.get("chunks", [])
    new_chunks = []
    split_count = 0

    for chunk in chunks:
        text = chunk.get("text", "")
        if len(text) > max_chars:
            sub_chunks = split_long_chunk(chunk, chunker, max_chars)
            new_chunks.extend(sub_chunks)
            split_count += 1
        else:
            new_chunks.append(chunk)

    if split_count == 0:
        return 0, len(chunks)

    # Reindex all chunks
    for i, chunk in enumerate(new_chunks):
        chunk["chunk_index"] = i

    if not dry_run:
        data["chunks"] = new_chunks
        data["total_chunks"] = len(new_chunks)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    return split_count, len(new_chunks)


def main():
    parser = argparse.ArgumentParser(description="Re-chunk long chunks")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help=f"Max chars per chunk (default: {DEFAULT_MAX_CHARS})")
    args = parser.parse_args()

    chunker = SemanticChunker(target_size=512, overlap=50)
    json_files = sorted(CLEANED_DIR.glob("*.json"))
    print(f"Scanning {len(json_files)} files for chunks >{args.max_chars} chars...")

    total_split = 0
    files_fixed = 0

    for filepath in json_files:
        split_count, new_total = fix_long_chunks(filepath, args.max_chars, chunker, args.dry_run)
        if split_count > 0:
            with open(filepath) as f:
                data = json.load(f)
            name = data.get("file_name", filepath.stem)[:60]
            print(f"  {name}: split {split_count} chunks -> {new_total} total")
            total_split += split_count
            files_fixed += 1

    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"\n{mode}: {total_split} chunks split across {files_fixed} files")


if __name__ == "__main__":
    main()
