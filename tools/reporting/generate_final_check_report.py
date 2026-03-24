#!/usr/bin/env python3
"""
Generate a comprehensive cross-reference report:
  Dataset (Google Sheets) vs Cleaned JSONs vs Pinecone

Tabs:
  1. Summary: overall stats and status
  2. Ingested Files: 134 files in cleaned JSONs with metadata + sample chunk
  3. Missing Files: 44 files from dataset not processed
  4. Pinecone Status: consistency check

Usage:
    PYTHONPATH=. python tools/reporting/generate_final_check_report.py
    PYTHONPATH=. python tools/reporting/generate_final_check_report.py --csv-only
"""

import csv
import json
import sys
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path

from tools.common.config import TMP_DIR

CLEANED_DIR = TMP_DIR / "cleaned"


def load_dataset():
    """Load dataset.json (file list from Google Sheets)."""
    path = TMP_DIR / "dataset.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def load_state():
    """Load state.json (ingestion tracking)."""
    path = TMP_DIR / "state.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def load_cleaned():
    """Load all cleaned JSONs. Returns dict of drive_id -> data."""
    cleaned = {}
    for fp in sorted(CLEANED_DIR.glob("*.json")):
        with open(fp) as f:
            data = json.load(f)
        cleaned[data["drive_id"]] = data
    return cleaned


def load_failed_downloads():
    """Load failed downloads list."""
    path = TMP_DIR / "failed_downloads.json"
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    return {f["drive_id"]: f for f in data.get("files", [])}


def get_pinecone_stats():
    """Get Pinecone namespace stats."""
    try:
        from tools.ingestion.pinecone_client import PineconeClient
        client = PineconeClient()
        stats = client.index.describe_index_stats()
        gp = stats.namespaces.get("genova-prod")
        return gp.vector_count if gp else 0
    except Exception as e:
        print(f"Warning: Could not connect to Pinecone: {e}", file=sys.stderr)
        return -1


def count_meta_values(chunks, field):
    """Count metadata values across chunks."""
    counts = Counter()
    for chunk in chunks:
        val = chunk.get("metadata", {}).get(field, "")
        if isinstance(val, list):
            for v in val:
                if v:
                    counts[v] += 1
        elif val:
            counts[val] += 1
    if not counts:
        return ""
    return ", ".join(f"{k}({v})" for k, v in counts.most_common())


def fecha_range(chunks):
    """Get fecha range from chunks."""
    fechas = set()
    for chunk in chunks:
        val = chunk.get("metadata", {}).get("fecha", "")
        if isinstance(val, list):
            fechas.update(v for v in val if v)
        elif val:
            fechas.add(val)
    if not fechas:
        return ""
    s = sorted(fechas)
    return s[0] if len(s) == 1 else f"{s[0]} to {s[-1]}"


def build_ingested_rows(cleaned, state):
    """Build rows for ingested files tab."""
    headers = [
        "File ID", "File Name", "File Type", "Total Chunks",
        "Chunking Method", "Metadata Method",
        "Country Distribution", "Bandera Distribution", "Fecha Range",
        "Team Distribution", "In Pinecone State",
        "Source URL", "Sample Chunk (first 300 chars)",
    ]

    rows = []
    for fid, data in sorted(cleaned.items(), key=lambda x: x[1].get("file_name", "")):
        chunks = data.get("chunks", [])
        in_state = "Yes" if fid in state.get("files", {}) else "No"

        sample = chunks[0]["text"][:300] if chunks else ""

        rows.append([
            fid,
            data.get("file_name", ""),
            data.get("file_type", ""),
            data.get("total_chunks", 0),
            data.get("chunking_method", ""),
            data.get("metadata_method", ""),
            count_meta_values(chunks, "country"),
            count_meta_values(chunks, "bandera"),
            fecha_range(chunks),
            count_meta_values(chunks, "team"),
            in_state,
            data.get("source_url", ""),
            sample,
        ])

    return headers, rows


def build_missing_rows(dataset, cleaned, failed):
    """Build rows for missing files tab."""
    headers = [
        "File ID", "File Name", "Source", "PIC",
        "Status", "Reason",
    ]

    dataset_files = dataset.get("files", [])
    cleaned_ids = set(cleaned.keys())

    rows = []
    for f in dataset_files:
        fid = f["drive_id"]
        if fid in cleaned_ids:
            continue

        if fid in failed:
            status = "Download Failed"
            reason = failed[fid].get("error", "exportSizeLimitExceeded")
        else:
            status = "Not Downloaded"
            reason = "Not in download manifest or processing failed"

        rows.append([
            fid,
            f.get("name", ""),
            f.get("source", ""),
            f.get("pic", ""),
            status,
            reason,
        ])

    return headers, rows


def build_summary(dataset, cleaned, state, pinecone_count, missing_count):
    """Build summary tab."""
    total_chunks = sum(len(d.get("chunks", [])) for d in cleaned.values())
    state_chunks = sum(f["chunk_count"] for f in state.get("files", {}).values())

    # File type breakdown
    type_counts = Counter(d.get("file_type", "") for d in cleaned.values())

    summary = [
        ["RAG Pipeline - Final Check Report"],
        ["Generated", datetime.now().strftime("%Y-%m-%d %H:%M")],
        [""],
        ["== Dataset Overview =="],
        ["Total files in Google Sheets", len(dataset.get("files", []))],
        ["Files processed (cleaned JSONs)", len(cleaned)],
        ["Files missing/failed", missing_count],
        ["Coverage", f"{len(cleaned) / max(len(dataset.get('files', [])), 1) * 100:.1f}%"],
        [""],
        ["== Chunk Stats =="],
        ["Total chunks in cleaned JSONs", total_chunks],
        ["Chunks tracked in state.json", state_chunks],
        ["Vectors in Pinecone", pinecone_count if pinecone_count >= 0 else "N/A"],
        [""],
        ["== Pinecone Sync Status =="],
    ]

    if pinecone_count >= 0:
        if pinecone_count == total_chunks:
            summary.append(["Status", "SYNCED - Pinecone matches cleaned JSONs"])
        elif pinecone_count == state_chunks:
            summary.append(["Status", "STALE - Pinecone matches old state, cleaned JSONs updated"])
            summary.append(["Action needed", f"Re-ingest to sync {total_chunks - pinecone_count} chunks"])
        else:
            summary.append(["Status", f"OUT OF SYNC - Pinecone has {pinecone_count}, expected {total_chunks}"])
            summary.append(["Action needed", "Run full re-ingestion (validation_and_reingest.md)"])
    else:
        summary.append(["Status", "UNKNOWN - Could not connect to Pinecone"])

    summary.extend([
        [""],
        ["== File Type Breakdown =="],
        ["Type", "Count"],
    ])
    for ft, count in type_counts.most_common():
        summary.append([ft, count])

    return summary


def write_csv(ingested_headers, ingested_rows, missing_headers, missing_rows):
    """Write to CSV files."""
    ingested_path = TMP_DIR / "final_check_ingested.csv"
    with open(ingested_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(ingested_headers)
        w.writerows(ingested_rows)
    print(f"CSV saved: {ingested_path}")

    missing_path = TMP_DIR / "final_check_missing.csv"
    with open(missing_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(missing_headers)
        w.writerows(missing_rows)
    print(f"CSV saved: {missing_path}")


def write_google_sheets(summary, ingested_headers, ingested_rows,
                         missing_headers, missing_rows, title=None):
    """Write report to Google Sheets."""
    from tools.common.google_auth import authenticate_google_sheets, retry_with_backoff

    gc = authenticate_google_sheets()
    if not gc:
        print("ERROR: Could not authenticate with Google Sheets", file=sys.stderr)
        return None

    if not title:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = f"RAG Final Check Report - {ts}"

    print(f"Creating Google Sheet: {title}")
    spreadsheet = gc.create(title)

    # Tab 1: Summary
    ws_summary = spreadsheet.sheet1
    ws_summary.update_title("Summary")
    retry_with_backoff(lambda: ws_summary.update(range_name="A1", values=summary))

    # Tab 2: Ingested Files
    ws_ingested = spreadsheet.add_worksheet(
        title="Ingested Files", rows=len(ingested_rows) + 2, cols=len(ingested_headers) + 1
    )
    all_ingested = [ingested_headers] + ingested_rows
    retry_with_backoff(lambda: ws_ingested.update(range_name="A1", values=all_ingested))

    # Tab 3: Missing Files
    if missing_rows:
        ws_missing = spreadsheet.add_worksheet(
            title="Missing Files", rows=len(missing_rows) + 2, cols=len(missing_headers) + 1
        )
        all_missing = [missing_headers] + missing_rows
        retry_with_backoff(lambda: ws_missing.update(range_name="A1", values=all_missing))

    url = spreadsheet.url
    print(f"\nGoogle Sheet created: {url}")
    return url


def main():
    parser = argparse.ArgumentParser(description="Generate final cross-reference report")
    parser.add_argument("--csv-only", action="store_true")
    parser.add_argument("--title", default=None)
    args = parser.parse_args()

    print("Loading data...")
    dataset = load_dataset()
    state = load_state()
    cleaned = load_cleaned()
    failed = load_failed_downloads()

    print("Checking Pinecone...")
    pinecone_count = get_pinecone_stats()

    dataset_ids = set(f["drive_id"] for f in dataset.get("files", []))
    cleaned_ids = set(cleaned.keys())
    missing_count = len(dataset_ids - cleaned_ids)

    print(f"\nDataset: {len(dataset_ids)} files")
    print(f"Cleaned: {len(cleaned_ids)} files")
    print(f"Missing: {missing_count} files")
    print(f"Pinecone: {pinecone_count} vectors")

    # Build all tabs
    summary = build_summary(dataset, cleaned, state, pinecone_count, missing_count)
    ingested_headers, ingested_rows = build_ingested_rows(cleaned, state)
    missing_headers, missing_rows = build_missing_rows(dataset, cleaned, failed)

    # Always write CSV
    write_csv(ingested_headers, ingested_rows, missing_headers, missing_rows)

    # Write Google Sheets
    if not args.csv_only:
        url = write_google_sheets(
            summary, ingested_headers, ingested_rows,
            missing_headers, missing_rows, args.title
        )
        if url:
            print(f"\n{url}")
    else:
        print("Skipping Google Sheets (--csv-only)")

    # Print summary
    total_chunks = sum(len(d.get("chunks", [])) for d in cleaned.values())
    print(f"\n{'='*50}")
    print(f"FINAL STATUS:")
    print(f"  Dataset coverage: {len(cleaned_ids)}/{len(dataset_ids)} ({len(cleaned_ids)/max(len(dataset_ids),1)*100:.1f}%)")
    print(f"  Cleaned chunks: {total_chunks}")
    print(f"  Pinecone vectors: {pinecone_count}")
    if pinecone_count != total_chunks and pinecone_count >= 0:
        print(f"  ACTION NEEDED: Re-ingest to Pinecone (run validation_and_reingest.md)")


if __name__ == "__main__":
    main()
