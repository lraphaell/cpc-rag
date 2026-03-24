#!/usr/bin/env python3
"""
Download files from Google Drive based on a change manifest or file ID list.

Handles both native files (PDF, DOCX) and Google Workspace files
(Docs→DOCX, Sheets→XLSX, Slides→PPTX).

Usage:
    # Download all changed files from change manifest:
    PYTHONPATH=. python tools/fetch/download_files.py

    # Download specific files by drive ID:
    PYTHONPATH=. python tools/fetch/download_files.py --files id1,id2,id3

    # Download from a dataset JSON (all files):
    PYTHONPATH=. python tools/fetch/download_files.py --all --dataset-json .tmp/dataset.json

Output:
    Files downloaded to .tmp/downloads/
    .tmp/download_manifest.json with results
"""

import io
import json
import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

from tools.common.config import TMP_DIR, DOWNLOADS_DIR
from tools.common.google_auth import authenticate_google_drive, retry_with_backoff


# Google Workspace export formats
EXPORT_FORMATS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}


def download_file(service, file_id, file_name, mime_type, dest_dir):
    """
    Download a single file from Google Drive.

    Args:
        service: Google Drive v3 service
        file_id: Drive file ID
        file_name: Filename for saving
        mime_type: MIME type of the file
        dest_dir: Destination directory

    Returns:
        dict: {success, local_path, file_name, was_exported, size_bytes} or {success: False, error}
    """
    from googleapiclient.http import MediaIoBaseDownload
    import re as _re

    try:
        was_exported = False

        if mime_type in EXPORT_FORMATS:
            export_mime, extension = EXPORT_FORMATS[mime_type]
            if not file_name.endswith(extension):
                file_name += extension
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
            was_exported = True
        else:
            request = service.files().get_media(fileId=file_id)

        # Sanitize filename: replace / \ | and other path-breaking chars
        file_name = _re.sub(r'[/\\|<>:*?"]+', '_', file_name).strip()

        # Handle duplicate filenames
        dest_path = dest_dir / file_name
        counter = 1
        while dest_path.exists():
            name_part, ext = os.path.splitext(file_name)
            dest_path = dest_dir / f"{name_part}_({counter}){ext}"
            counter += 1

        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        content = fh.getvalue()
        with open(dest_path, "wb") as f:
            f.write(content)

        return {
            "success": True,
            "local_path": str(dest_path),
            "file_name": dest_path.name,
            "was_exported": was_exported,
            "size_bytes": len(content),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def download_files(file_list, dest_dir=None):
    """
    Download a list of files from Google Drive.

    Args:
        file_list: List of dicts with at least {drive_id, name}
                   Optional: {mime_type} — if missing, will be fetched from Drive
        dest_dir: Destination directory (default: DOWNLOADS_DIR)

    Returns:
        dict: {downloaded, failed, results: [{drive_id, name, ...}]}
    """
    if dest_dir is None:
        dest_dir = DOWNLOADS_DIR
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    service = authenticate_google_drive()
    if not service:
        print("ERROR: Could not authenticate with Google Drive", file=sys.stderr)
        sys.exit(1)

    results = []
    downloaded = 0
    failed = 0

    print(f"Downloading {len(file_list)} files to {dest_dir}...")

    for i, file_info in enumerate(file_list, 1):
        drive_id = file_info["drive_id"]
        name = file_info.get("name", f"file_{drive_id}")
        mime_type = file_info.get("mime_type", "")

        # If mime_type not provided, fetch from Drive
        if not mime_type:
            try:
                meta = retry_with_backoff(
                    lambda fid=drive_id: service.files().get(
                        fileId=fid,
                        fields="mimeType,name",
                        supportsAllDrives=True,
                    ).execute()
                )
                mime_type = meta.get("mimeType", "")
                if not name or name == f"file_{drive_id}":
                    name = meta.get("name", name)
            except Exception as e:
                print(f"  [{i}/{len(file_list)}] FAIL: {name} — could not get metadata: {e}")
                results.append({"drive_id": drive_id, "name": name, "success": False, "error": str(e)})
                failed += 1
                continue

        print(f"  [{i}/{len(file_list)}] Downloading: {name}...", end=" ")

        result = retry_with_backoff(
            lambda fid=drive_id, fn=name, mt=mime_type: download_file(
                service, fid, fn, mt, dest_dir
            )
        )

        result["drive_id"] = drive_id
        result["name"] = name
        result["mime_type"] = mime_type
        results.append(result)

        if result["success"]:
            downloaded += 1
            print(f"OK ({result['size_bytes']} bytes)")
        else:
            failed += 1
            print(f"FAIL ({result.get('error', '?')})")

    print(f"\nDownloaded: {downloaded}, Failed: {failed}")

    return {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "dest_dir": str(dest_dir),
        "downloaded": downloaded,
        "failed": failed,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Download files from Google Drive")
    parser.add_argument("--files", default=None,
                        help="Comma-separated Drive file IDs")
    parser.add_argument("--change-manifest", default=str(TMP_DIR / "change_manifest.json"),
                        help="Path to change_manifest.json from detect_changes.py")
    parser.add_argument("--dataset-json", default=str(TMP_DIR / "dataset.json"),
                        help="Path to dataset.json (used with --all)")
    parser.add_argument("--all", action="store_true",
                        help="Download all files from dataset (not just changes)")
    args = parser.parse_args()

    if args.files:
        # Download specific files by ID
        file_list = [{"drive_id": fid.strip(), "name": ""} for fid in args.files.split(",")]
    elif args.all:
        # Download all files from dataset
        with open(args.dataset_json, "r") as f:
            dataset = json.load(f)
        file_list = dataset.get("files", [])
    else:
        # Download changed files from change manifest
        try:
            with open(args.change_manifest, "r") as f:
                manifest = json.load(f)
        except FileNotFoundError:
            print(f"ERROR: Change manifest not found: {args.change_manifest}", file=sys.stderr)
            print("Run detect_changes.py first, or use --all to download everything.", file=sys.stderr)
            sys.exit(1)

        changes = manifest.get("changes", [])
        file_list = [
            c["file_info"] for c in changes
            if c["action"] in ("add", "update")
        ]

        if not file_list:
            print("No files to download (no add/update changes detected).")
            return

    result = download_files(file_list)

    # Save download manifest
    manifest_path = TMP_DIR / "download_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nDownload manifest saved to: {manifest_path}")


if __name__ == "__main__":
    main()
