#!/usr/bin/env python3
"""
Remove tabular/transactional chunks from Pinecone.

Identifies chunks with >12% digit ratio (raw spreadsheet data) and
deletes them from Pinecone. Updates state.json to reflect the removal.

These chunks pollute semantic search results without adding QA value.

Usage:
    PYTHONPATH=. python tools/cleanup/remove_tabular_chunks.py --dry-run
    PYTHONPATH=. python tools/cleanup/remove_tabular_chunks.py
"""

import json
import sys
import argparse
import time
from pathlib import Path

from tools.common.config import TMP_DIR, PINECONE_NAMESPACE

CLEANED_DIR = TMP_DIR / "cleaned"
DIGIT_THRESHOLD = 0.12


def is_tabular(text):
    """Check if text is raw tabular data."""
    if not text or len(text) < 50:
        return False
    return sum(1 for ch in text if ch.isdigit()) / len(text) > DIGIT_THRESHOLD


def main():
    parser = argparse.ArgumentParser(description="Remove tabular chunks from Pinecone")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load state
    state_path = TMP_DIR / "state.json"
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)
    else:
        state = {"last_run": "", "files": {}}

    # Find tabular chunk IDs across all files
    ids_to_delete = []
    files_affected = {}

    for fp in sorted(CLEANED_DIR.glob("*.json")):
        with open(fp) as f:
            data = json.load(f)

        drive_id = data["drive_id"]
        chunks = data.get("chunks", [])
        file_tab_ids = []
        file_keep_ids = []

        for chunk in chunks:
            idx = chunk.get("chunk_index", 0)
            cid = f"{drive_id}_{idx:04d}"
            if is_tabular(chunk.get("text", "")):
                file_tab_ids.append(cid)
            else:
                file_keep_ids.append(cid)

        if file_tab_ids:
            ids_to_delete.extend(file_tab_ids)
            files_affected[drive_id] = {
                "name": data.get("file_name", "")[:60],
                "removed": len(file_tab_ids),
                "kept": len(file_keep_ids),
                "keep_ids": file_keep_ids,
            }

    print(f"Chunks to remove: {len(ids_to_delete)} tabular chunks in {len(files_affected)} files")
    print(f"Chunks to keep: {sum(f['kept'] for f in files_affected.values())} narrative chunks in affected files")

    if args.dry_run:
        print("\nDRY RUN - no changes made")
        print("\nFiles affected:")
        for fid, info in sorted(files_affected.items(), key=lambda x: -x[1]["removed"]):
            print(f"  {info['removed']}/{info['removed']+info['kept']} removed | {info['name']}")
        return

    # Delete from Pinecone
    from tools.ingestion.pinecone_client import PineconeClient
    client = PineconeClient()

    print(f"\nDeleting {len(ids_to_delete)} vectors from Pinecone...")
    # Delete in batches of 1000
    for i in range(0, len(ids_to_delete), 1000):
        batch = ids_to_delete[i:i + 1000]
        client.delete_by_ids(batch, namespace=PINECONE_NAMESPACE)
        print(f"  Deleted batch {i // 1000 + 1}: {len(batch)} vectors")
        if i + 1000 < len(ids_to_delete):
            time.sleep(2)

    # Update state.json - update chunk counts and IDs
    for drive_id, info in files_affected.items():
        if drive_id in state["files"]:
            state["files"][drive_id]["pinecone_chunk_ids"] = info["keep_ids"]
            state["files"][drive_id]["chunk_count"] = len(info["keep_ids"])

            # If all chunks removed, remove file from state
            if not info["keep_ids"]:
                del state["files"][drive_id]
                print(f"  Removed from state: {info['name']} (all chunks tabular)")

    with open(TMP_DIR / "state.json", "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    # Verify
    time.sleep(5)
    stats = client.index.describe_index_stats()
    gp = stats.namespaces.get(PINECONE_NAMESPACE)
    pinecone_count = gp.vector_count if gp else 0
    state_chunks = sum(f["chunk_count"] for f in state["files"].values())

    print(f"\nDone!")
    print(f"  Pinecone vectors: {pinecone_count}")
    print(f"  State.json chunks: {state_chunks}")
    print(f"  Match: {pinecone_count == state_chunks}")


if __name__ == "__main__":
    main()
