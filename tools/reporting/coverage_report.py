#!/usr/bin/env python3
"""
Coverage report: cross-reference dataset vs downloads vs cleaned JSONs.

Shows real-time file coverage status across the pipeline.

Usage:
    PYTHONPATH=. python tools/reporting/coverage_report.py
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

from tools.common.config import TMP_DIR, DOWNLOADS_DIR

CLEANED_DIR = TMP_DIR / "cleaned"
DATASET_PATH = TMP_DIR / "dataset.json"
RETRY_RESULTS = TMP_DIR / "retry_download_results.json"
MANUAL_MANIFEST = TMP_DIR / "manual_download_manifest.json"


def main():
    # 1. Load dataset
    if not DATASET_PATH.exists():
        print("ERROR: dataset.json not found. Run fetch_dataset.py first.")
        sys.exit(1)

    with open(DATASET_PATH) as f:
        dataset = json.load(f)
    all_files = dataset.get("files", [])
    dataset_ids = {f["drive_id"]: f for f in all_files}

    # 2. Count cleaned JSONs
    cleaned_ids = set()
    cleaned_stats = {}
    if CLEANED_DIR.exists():
        for jp in CLEANED_DIR.glob("*.json"):
            did = jp.stem
            cleaned_ids.add(did)
            try:
                with open(jp) as f:
                    data = json.load(f)
                cleaned_stats[did] = {
                    "chunks": data.get("total_chunks", 0),
                    "method": data.get("chunking_method", ""),
                    "status": data.get("metadata_status", ""),
                    "type": data.get("file_type", ""),
                }
            except Exception:
                cleaned_stats[did] = {"chunks": 0, "method": "?", "status": "?", "type": "?"}

    # 3. Count downloads
    downloaded_files = set()
    if DOWNLOADS_DIR.exists():
        downloaded_files = {f.name for f in DOWNLOADS_DIR.iterdir() if f.is_file()}

    # 4. Load retry results
    retry_success = set()
    retry_failed_403 = set()
    retry_failed_404 = set()
    if RETRY_RESULTS.exists():
        with open(RETRY_RESULTS) as f:
            retry = json.load(f)
        for e in retry.get("success", []):
            retry_success.add(e["drive_id"])
        for e in retry.get("failed", []):
            did = e["drive_id"]
            if "404" in e.get("error", ""):
                retry_failed_404.add(did)
            else:
                retry_failed_403.add(did)

    # 5. Classify each file
    statuses = Counter()
    missing_details = []

    for did, info in dataset_ids.items():
        name = info.get("name", "?")
        dtype = info.get("drive_type", "?")

        if did in cleaned_ids:
            statuses["cleaned"] += 1
        elif did in retry_failed_404:
            statuses["404_deleted"] += 1
        elif did in retry_failed_403:
            statuses["403_blocked"] += 1
            missing_details.append({"name": name, "type": dtype, "reason": "403 org policy", "drive_id": did})
        elif did in retry_success:
            statuses["downloaded_not_cleaned"] += 1
            missing_details.append({"name": name, "type": dtype, "reason": "downloaded but not chunked", "drive_id": did})
        else:
            statuses["not_attempted"] += 1
            missing_details.append({"name": name, "type": dtype, "reason": "not downloaded", "drive_id": did})

    # 6. Print report
    total = len(dataset_ids)
    cleaned = statuses["cleaned"]
    pct = (cleaned / total * 100) if total else 0

    print("=" * 60)
    print("COVERAGE REPORT")
    print("=" * 60)
    print(f"Dataset total:              {total}")
    print(f"Cleaned JSONs:              {cleaned} ({pct:.1f}%)")
    print(f"Downloaded (not cleaned):   {statuses['downloaded_not_cleaned']}")
    print(f"403 blocked (org policy):   {statuses['403_blocked']}")
    print(f"404 deleted/moved:          {statuses['404_deleted']}")
    print(f"Not attempted:              {statuses['not_attempted']}")
    print(f"Downloads dir files:        {len(downloaded_files)}")
    print()

    # Cleaned stats
    if cleaned_stats:
        total_chunks = sum(s["chunks"] for s in cleaned_stats.values())
        types = Counter(s["type"] for s in cleaned_stats.values())
        methods = Counter(s["method"] for s in cleaned_stats.values())
        meta_statuses = Counter(s["status"] for s in cleaned_stats.values())

        print(f"Total chunks:               {total_chunks}")
        print(f"File types:                 {dict(types)}")
        print(f"Chunking methods:           {dict(methods)}")
        print(f"Metadata statuses:          {dict(meta_statuses)}")
        print()

    # Missing files
    if missing_details:
        print(f"--- {len(missing_details)} files NOT cleaned ---")
        by_reason = {}
        for d in missing_details:
            reason = d["reason"]
            if reason not in by_reason:
                by_reason[reason] = []
            by_reason[reason].append(d)

        for reason, files in by_reason.items():
            print(f"\n  [{reason}] ({len(files)} files)")
            for f in files[:10]:
                print(f"    {f['name'][:60]} ({f['type']})")
            if len(files) > 10:
                print(f"    ... and {len(files) - 10} more")

    print()
    max_possible = total - statuses["404_deleted"]
    max_pct = (cleaned / max_possible * 100) if max_possible else 0
    print(f"Max achievable coverage:    {max_possible} files ({cleaned}/{max_possible} = {max_pct:.1f}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
