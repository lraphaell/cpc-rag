#!/usr/bin/env python3
"""
Read the Google Sheets dataset index and return structured file list.

The dataset sheet contains rows with: Source, Dataset, URL, PIC
This tool parses Drive file IDs from URLs and returns a JSON list.

Usage:
    PYTHONPATH=. python tools/fetch/fetch_dataset.py

Output:
    .tmp/dataset.json with structured file list
"""

import json
import re
import sys
from datetime import datetime, timezone

from tools.common.config import DATASET_SHEET_ID, TMP_DIR
from tools.common.google_auth import authenticate_google_sheets, authenticate_google_drive, retry_with_backoff


def parse_drive_id(url):
    """
    Extract Google Drive file ID from various URL formats.

    Supported formats:
    - https://docs.google.com/document/d/{ID}/...
    - https://docs.google.com/spreadsheets/d/{ID}/...
    - https://docs.google.com/presentation/d/{ID}/...
    - https://drive.google.com/file/d/{ID}/...
    - https://drive.google.com/open?id={ID}
    - https://drive.google.com/drive/folders/{ID}

    Returns:
        tuple: (file_id, file_type) or (None, None)
    """
    if not url:
        return None, None

    # Pattern: /d/{ID}/
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if match:
        file_id = match.group(1)
        # Detect type from URL
        if 'document' in url:
            return file_id, 'google_doc'
        elif 'spreadsheets' in url:
            return file_id, 'google_sheet'
        elif 'presentation' in url:
            return file_id, 'google_slides'
        elif 'file' in url:
            return file_id, 'drive_file'
        return file_id, 'unknown'

    # Pattern: ?id={ID}
    match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1), 'drive_file'

    # Pattern: /folders/{ID}
    match = re.search(r'/folders/([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1), 'folder'

    return None, None


def expand_folder(drive_service, folder_id, folder_name, source, pic):
    """
    List all files inside a Google Drive folder recursively.

    Args:
        drive_service: Google Drive v3 service
        folder_id: Folder Drive ID
        folder_name: Parent folder name (for context)
        source: Source from the Sheet row
        pic: PIC from the Sheet row

    Returns:
        List of file dicts (same structure as sheet entries)
    """
    files = []
    page_token = None

    supported_mimes = [
        "application/pdf",
        "text/plain",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.spreadsheet",
        "application/vnd.google-apps.presentation",
        "application/vnd.google-apps.folder",
    ]

    try:
        while True:
            results = retry_with_backoff(
                lambda pt=page_token: drive_service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    pageSize=100,
                    fields="nextPageToken, files(id, name, mimeType)",
                    pageToken=pt,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
            )

            for item in results.get("files", []):
                mime = item["mimeType"]
                if mime == "application/vnd.google-apps.folder":
                    # Recurse into subfolder
                    sub_files = expand_folder(
                        drive_service, item["id"],
                        f"{folder_name}/{item['name']}", source, pic
                    )
                    files.extend(sub_files)
                elif mime in supported_mimes:
                    # Determine drive_type
                    if "document" in mime:
                        dtype = "google_doc"
                    elif "spreadsheet" in mime:
                        dtype = "google_sheet"
                    elif "presentation" in mime:
                        dtype = "google_slides"
                    else:
                        dtype = "drive_file"

                    # Sanitize name: use " - " instead of " / " to avoid path issues
                    safe_name = re.sub(r'[/\\|<>:*?"]+', '_', f"{folder_name} - {item['name']}")
                    files.append({
                        "name": safe_name,
                        "drive_id": item["id"],
                        "url": f"https://drive.google.com/file/d/{item['id']}",
                        "source": source,
                        "pic": pic,
                        "drive_type": dtype,
                        "parent_folder": folder_name,
                    })

            page_token = results.get("nextPageToken")
            if not page_token:
                break

    except Exception as e:
        print(f"  Warning: Could not list folder '{folder_name}': {e}", file=sys.stderr)

    return files


def fetch_dataset(expand_folders=True):
    """
    Read the Google Sheets dataset index and return structured file list.

    Args:
        expand_folders: If True, list contents of folder entries recursively

    Returns:
        dict: {fetched_at, total_files, files: [{name, drive_id, url, source, pic, drive_type}]}
    """
    gc = authenticate_google_sheets()
    if not gc:
        print("ERROR: Could not authenticate with Google Sheets", file=sys.stderr)
        sys.exit(1)

    print(f"Reading dataset from Google Sheets: {DATASET_SHEET_ID}")
    sp = gc.open_by_key(DATASET_SHEET_ID)
    ws = sp.sheet1
    records = ws.get_all_records()

    files = []
    folders_to_expand = []
    skipped = 0

    for i, row in enumerate(records, start=2):  # start=2 because row 1 is header
        url = row.get("URL", "").strip()
        name = row.get("Dataset", "").strip()
        source = row.get("Source", "").strip()
        pic = row.get("PIC", "").strip()

        if not url:
            skipped += 1
            continue

        drive_id, drive_type = parse_drive_id(url)

        if not drive_id:
            print(f"  Warning: Could not parse Drive ID from row {i}: {url[:60]}...")
            skipped += 1
            continue

        if drive_type == "folder":
            folders_to_expand.append({
                "name": name,
                "drive_id": drive_id,
                "source": source,
                "pic": pic,
            })
        else:
            files.append({
                "name": name,
                "drive_id": drive_id,
                "url": url,
                "source": source,
                "pic": pic,
                "drive_type": drive_type,
                "sheet_row": i,
            })

    # Expand folders if requested
    if expand_folders and folders_to_expand:
        drive_service = authenticate_google_drive()
        if drive_service:
            print(f"\nExpanding {len(folders_to_expand)} folders...")
            for folder in folders_to_expand:
                print(f"  Listing: {folder['name']}...")
                folder_files = expand_folder(
                    drive_service, folder["drive_id"],
                    folder["name"], folder["source"], folder["pic"]
                )
                print(f"    Found {len(folder_files)} files inside")
                files.extend(folder_files)
        else:
            print("  Warning: Could not auth for Drive, skipping folder expansion")

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sheet_id": DATASET_SHEET_ID,
        "total_files": len(files),
        "skipped": skipped,
        "folders_expanded": len(folders_to_expand),
        "files": files,
    }

    print(f"\nFound {len(files)} files ({skipped} skipped, {len(folders_to_expand)} folders expanded)")
    return result


def main():
    result = fetch_dataset()

    # Save to .tmp/dataset.json
    output_path = TMP_DIR / "dataset.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nDataset saved to: {output_path}")

    # Print summary
    from collections import Counter
    type_counts = Counter(f["drive_type"] for f in result["files"])
    print(f"\nFile types:")
    for t, count in type_counts.most_common():
        print(f"  {t}: {count}")


if __name__ == "__main__":
    main()
