#!/usr/bin/env python3
"""
Detect changes in dataset files by comparing Google Drive modifiedTime
against the local state.json.

Returns a list of actions: add, update, or delete.

Usage:
    PYTHONPATH=. python tools/state/detect_changes.py [--dataset-json path]

    --dataset-json: Path to dataset JSON from fetch_dataset.py (default: .tmp/dataset.json)

Output:
    .tmp/change_manifest.json with list of {action, file_info} entries
"""

import json
import sys
from datetime import datetime, timezone

from tools.common.config import STATE_FILE, TMP_DIR, DOWNLOADS_DIR
from tools.common.google_auth import authenticate_google_drive, retry_with_backoff


def load_state():
    """Load existing state from state.json, or return empty state."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_run": None, "files": {}}


def get_drive_modified_time(drive_service, file_id):
    """Get the modifiedTime of a file from Google Drive."""
    try:
        result = retry_with_backoff(
            lambda: drive_service.files().get(
                fileId=file_id,
                fields="modifiedTime,name,mimeType,size",
                supportsAllDrives=True,
            ).execute()
        )
        return result
    except Exception as e:
        print(f"  Warning: Could not get metadata for {file_id}: {e}", file=sys.stderr)
        return None


def detect_changes(dataset_files, state=None):
    """
    Compare dataset files against local state to find changes.

    Args:
        dataset_files: List of dicts from fetch_dataset.py
                       [{name, drive_id, url, source, pic, ...}]
        state: Current state dict (loaded from state.json)

    Returns:
        List of {action: "add"|"update"|"delete", file_info: dict}
    """
    if state is None:
        state = load_state()

    drive_service = authenticate_google_drive()
    if not drive_service:
        print("ERROR: Could not authenticate with Google Drive", file=sys.stderr)
        sys.exit(1)

    changes = []
    current_drive_ids = set()

    print(f"Checking {len(dataset_files)} files for changes...")

    for file_info in dataset_files:
        drive_id = file_info.get("drive_id")
        if not drive_id:
            print(f"  Skipping '{file_info.get('name', '?')}': no drive_id", file=sys.stderr)
            continue

        current_drive_ids.add(drive_id)
        drive_meta = get_drive_modified_time(drive_service, drive_id)

        if drive_meta is None:
            print(f"  Skipping '{file_info.get('name', '?')}': could not read Drive metadata")
            continue

        modified_time = drive_meta.get("modifiedTime", "")
        file_info["modified_time"] = modified_time
        file_info["mime_type"] = drive_meta.get("mimeType", "")
        file_info["size"] = drive_meta.get("size", "0")

        state_entry = state["files"].get(drive_id)

        if state_entry is None:
            # New file — never processed before
            changes.append({"action": "add", "file_info": file_info})
            print(f"  + ADD: {file_info.get('name', drive_id)}")
        elif modified_time > state_entry.get("modified_time", ""):
            # File has been modified since last ingestion
            changes.append({"action": "update", "file_info": file_info})
            print(f"  ~ UPDATE: {file_info.get('name', drive_id)} (modified since {state_entry.get('modified_time', '?')})")
        else:
            print(f"  = UNCHANGED: {file_info.get('name', drive_id)}")

    # Check for deleted files (in state but not in current dataset)
    for drive_id, state_entry in state["files"].items():
        if drive_id not in current_drive_ids:
            changes.append({
                "action": "delete",
                "file_info": {
                    "drive_id": drive_id,
                    "name": state_entry.get("name", "unknown"),
                }
            })
            print(f"  - DELETE: {state_entry.get('name', drive_id)} (removed from dataset)")

    print(f"\nSummary: {len(changes)} changes detected "
          f"({sum(1 for c in changes if c['action']=='add')} add, "
          f"{sum(1 for c in changes if c['action']=='update')} update, "
          f"{sum(1 for c in changes if c['action']=='delete')} delete)")

    return changes


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Detect changes in dataset files")
    parser.add_argument("--dataset-json", default=str(TMP_DIR / "dataset.json"),
                        help="Path to dataset JSON from fetch_dataset.py")
    args = parser.parse_args()

    # Load dataset
    dataset_path = args.dataset_json
    try:
        with open(dataset_path, "r") as f:
            dataset = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Dataset file not found: {dataset_path}", file=sys.stderr)
        print("Run fetch_dataset.py first.", file=sys.stderr)
        sys.exit(1)

    dataset_files = dataset.get("files", [])
    state = load_state()
    changes = detect_changes(dataset_files, state)

    # Save change manifest
    manifest_path = TMP_DIR / "change_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump({
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "total_in_dataset": len(dataset_files),
            "changes": changes,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nChange manifest saved to: {manifest_path}")


if __name__ == "__main__":
    main()
