#!/usr/bin/env python3
"""
Process manually downloaded files that couldn't be fetched via API.

Reads .tmp/manual_download_manifest.json, finds matching files in
.tmp/downloads/, and runs them through prepare_file() to generate
cleaned JSONs.

Usage:
    PYTHONPATH=. python tools/cleanup/process_manual_downloads.py
    PYTHONPATH=. python tools/cleanup/process_manual_downloads.py --dry-run
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

from tools.common.config import TMP_DIR, DOWNLOADS_DIR
from tools.cleanup.prepare_chunks import prepare_file

MANIFEST_PATH = TMP_DIR / "manual_download_manifest.json"
RETRY_RESULTS_PATH = TMP_DIR / "retry_download_results.json"
CLEANED_DIR = TMP_DIR / "cleaned"


def _load_download_map():
    """Load drive_id -> local_path mapping from retry_download_results.json."""
    mapping = {}
    if RETRY_RESULTS_PATH.exists():
        with open(RETRY_RESULTS_PATH) as f:
            results = json.load(f)
        for entry in results.get("success", []):
            path = entry.get("path")
            if path and os.path.exists(path):
                mapping[entry["drive_id"]] = Path(path)
    return mapping


def find_file_for_entry(entry, download_map=None):
    """
    Find the downloaded file matching a manifest entry.

    Searches using:
    1. Download results map (drive_id -> exact path from API download)
    2. Exact drive_id as filename stem ({drive_id}.ext)
    3. Drive_id contained in filename
    4. Exact file name match (stem must equal document name)
    """
    drive_id = entry["drive_id"]
    name = entry["name"]
    expected_ext = entry.get("expected_ext", "")

    # Strategy 0: Use download results mapping (most reliable)
    if download_map and drive_id in download_map:
        return download_map[drive_id]

    if not DOWNLOADS_DIR.exists():
        return None

    candidates = [f for f in DOWNLOADS_DIR.iterdir() if f.is_file()]

    # Strategy 1: drive_id as filename stem
    for f in candidates:
        if f.stem == drive_id:
            return f

    # Strategy 2: drive_id contained in filename
    for f in candidates:
        if drive_id in f.name:
            return f

    # Strategy 3: EXACT name match only (no substring matching to avoid false positives)
    import re
    def normalize(s):
        return re.sub(r'[/\\|<>:*?"_\s]+', '', s).lower()

    name_norm = normalize(name)
    for f in candidates:
        if expected_ext and f.suffix.lower() != expected_ext.lower():
            continue
        stem_norm = normalize(f.stem)
        if stem_norm == name_norm:
            return f

    return None


def main():
    parser = argparse.ArgumentParser(description="Process manually downloaded files")
    parser.add_argument("--dry-run", action="store_true", help="Only show what would be processed")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH), help="Path to manual download manifest")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        print("Run the pipeline validation first to generate the manifest.")
        sys.exit(1)

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    entries = manifest.get("changes", [])
    print(f"Manual download manifest: {len(entries)} files")
    print(f"Downloads dir: {DOWNLOADS_DIR}")
    print()

    # Check which already have cleaned JSONs
    already_cleaned = set()
    if CLEANED_DIR.exists():
        already_cleaned = {f.stem for f in CLEANED_DIR.glob("*.json")}

    # Load download results mapping (drive_id -> local path)
    download_map = _load_download_map()
    if download_map:
        print(f"Download results map: {len(download_map)} files mapped")

    found = []
    not_found = []
    already_done = []

    for entry in entries:
        drive_id = entry["drive_id"]
        name = entry["name"]

        if drive_id in already_cleaned:
            already_done.append(entry)
            continue

        file_path = find_file_for_entry(entry, download_map)
        if file_path:
            found.append((entry, file_path))
        else:
            not_found.append(entry)

    print(f"Already cleaned: {len(already_done)}")
    print(f"Found downloads: {len(found)}")
    print(f"NOT found:       {len(not_found)}")
    print()

    if not_found:
        print("--- Files NOT found in downloads ---")
        for entry in not_found:
            print(f"  [{entry.get('drive_type', '?')}] {entry['name']}")
            print(f"    URL: {entry.get('url', 'N/A')}")
            print(f"    Expected: {entry['drive_id']}{entry.get('expected_ext', '')}")
        print()

    if found:
        print("--- Files ready to process ---")
        for entry, path in found:
            print(f"  {entry['name']} -> {path.name}")
        print()

    if args.dry_run:
        print("DRY RUN — no files processed.")
        return

    if not found:
        print("No new files to process. Download the missing files first.")
        return

    # Process found files
    results = []
    for entry, file_path in found:
        file_info = {
            "drive_id": entry["drive_id"],
            "name": entry["name"],
            "url": entry.get("url", ""),
            "source": entry.get("source", ""),
            "pic": entry.get("pic", ""),
        }

        try:
            result = prepare_file(str(file_path), file_info)
            result["drive_id"] = entry["drive_id"]
            result["file_name"] = entry["name"]
            results.append(result)
            print(f"  -> {result['status']}: {result.get('chunk_count', 0)} chunks")
        except Exception as e:
            results.append({
                "drive_id": entry["drive_id"],
                "file_name": entry["name"],
                "status": "error",
                "error": str(e),
            })
            print(f"  -> ERROR: {e}")

    # Summary
    prepared = sum(1 for r in results if r["status"] == "prepared")
    errors = sum(1 for r in results if r["status"] == "error")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    total_chunks = sum(r.get("chunk_count", 0) for r in results)

    print(f"\n{'='*50}")
    print(f"Processed: {len(results)} files")
    print(f"  Prepared: {prepared} ({total_chunks} chunks)")
    print(f"  Skipped:  {skipped}")
    print(f"  Errors:   {errors}")

    # Save processing log
    log = {
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "total_processed": len(results),
        "prepared": prepared,
        "errors": errors,
        "skipped": skipped,
        "total_chunks": total_chunks,
        "still_missing": len(not_found),
        "results": results,
    }
    log_path = TMP_DIR / "manual_processing_log.json"
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    print(f"\nLog saved to: {log_path}")


if __name__ == "__main__":
    main()
