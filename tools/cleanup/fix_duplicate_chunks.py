#!/usr/bin/env python3
"""
Remove duplicate chunks within the same cleaned JSON file.

Detects chunks with identical text (>20 chars) and keeps only the first
occurrence. Updates chunk_index and total_chunks after removal.

Usage:
    PYTHONPATH=. python tools/cleanup/fix_duplicate_chunks.py
    PYTHONPATH=. python tools/cleanup/fix_duplicate_chunks.py --dry-run
"""

import json
import sys
import argparse
from pathlib import Path

from tools.common.config import TMP_DIR

CLEANED_DIR = TMP_DIR / "cleaned"
MIN_TEXT_LEN = 20


def fix_duplicates(filepath, dry_run=False):
    """Remove duplicate chunks from a single file. Returns (removed_count, kept_count)."""
    with open(filepath) as f:
        data = json.load(f)

    chunks = data.get("chunks", [])
    if len(chunks) <= 1:
        return 0, len(chunks)

    seen_texts = set()
    unique_chunks = []
    removed = 0

    for chunk in chunks:
        text = chunk.get("text", "")
        if len(text) > MIN_TEXT_LEN and text in seen_texts:
            removed += 1
        else:
            if len(text) > MIN_TEXT_LEN:
                seen_texts.add(text)
            unique_chunks.append(chunk)

    if removed == 0:
        return 0, len(chunks)

    # Reindex
    for i, chunk in enumerate(unique_chunks):
        chunk["chunk_index"] = i

    if not dry_run:
        data["chunks"] = unique_chunks
        data["total_chunks"] = len(unique_chunks)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    return removed, len(unique_chunks)


def main():
    parser = argparse.ArgumentParser(description="Remove duplicate chunks")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    json_files = sorted(CLEANED_DIR.glob("*.json"))
    print(f"Scanning {len(json_files)} files for duplicates...")

    total_removed = 0
    files_fixed = 0

    for filepath in json_files:
        removed, kept = fix_duplicates(filepath, args.dry_run)
        if removed > 0:
            with open(filepath) as f:
                data = json.load(f)
            name = data.get("file_name", filepath.stem)[:60]
            print(f"  {name}: removed {removed} dupes, {kept} chunks remain")
            total_removed += removed
            files_fixed += 1

    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"\n{mode}: {total_removed} duplicate chunks removed from {files_fixed} files")


if __name__ == "__main__":
    main()
