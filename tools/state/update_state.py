#!/usr/bin/env python3
"""
Update state.json after successful ingestion.

Called per-file after successful Pinecone ingestion to ensure
state stays consistent even if the pipeline fails mid-run.

Usage:
    # From Python:
    from tools.state.update_state import update_file_state, remove_file_state

    update_file_state(drive_id, {
        "name": "doc.pdf",
        "modified_time": "2026-03-01T...",
        "content_hash": "sha256...",
        "pinecone_chunk_ids": ["id1", "id2"],
        "chunk_count": 12,
    })

    # CLI:
    PYTHONPATH=. python tools/state/update_state.py --ingestion-log .tmp/ingestion_log.json
"""

import json
import hashlib
from datetime import datetime, timezone

from tools.common.config import STATE_FILE


def load_state():
    """Load existing state from state.json."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_run": None, "files": {}}


def save_state(state):
    """Persist state to state.json."""
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def update_file_state(drive_id, file_data):
    """
    Update state for a single file after successful ingestion.

    Args:
        drive_id: Google Drive file ID
        file_data: dict with keys:
            - name: filename
            - modified_time: Drive modifiedTime
            - content_hash: sha256 of downloaded file (optional)
            - pinecone_chunk_ids: list of chunk IDs in Pinecone
            - chunk_count: number of chunks ingested
    """
    state = load_state()
    state["files"][drive_id] = {
        "name": file_data.get("name", ""),
        "drive_id": drive_id,
        "modified_time": file_data.get("modified_time", ""),
        "content_hash": file_data.get("content_hash", ""),
        "pinecone_chunk_ids": file_data.get("pinecone_chunk_ids", []),
        "last_ingested": datetime.now(timezone.utc).isoformat(),
        "chunk_count": file_data.get("chunk_count", 0),
    }
    save_state(state)


def remove_file_state(drive_id):
    """Remove a file from state (after deleting its chunks from Pinecone)."""
    state = load_state()
    if drive_id in state["files"]:
        del state["files"][drive_id]
        save_state(state)


def compute_file_hash(file_path):
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Update state from ingestion log")
    parser.add_argument("--ingestion-log", required=True,
                        help="Path to ingestion_log.json")
    args = parser.parse_args()

    with open(args.ingestion_log, "r") as f:
        log = json.load(f)

    state = load_state()

    for entry in log.get("processed_files", []):
        if entry.get("status") == "success":
            drive_id = entry.get("drive_id")
            if drive_id:
                state["files"][drive_id] = {
                    "name": entry.get("file_name", ""),
                    "drive_id": drive_id,
                    "modified_time": entry.get("modified_time", ""),
                    "content_hash": entry.get("content_hash", ""),
                    "pinecone_chunk_ids": entry.get("chunk_ids", []),
                    "last_ingested": datetime.now(timezone.utc).isoformat(),
                    "chunk_count": entry.get("chunk_count", 0),
                }

    for entry in log.get("deleted_files", []):
        drive_id = entry.get("drive_id")
        if drive_id and drive_id in state["files"]:
            del state["files"][drive_id]

    save_state(state)
    print(f"State updated: {len(state['files'])} files tracked")


if __name__ == "__main__":
    main()
