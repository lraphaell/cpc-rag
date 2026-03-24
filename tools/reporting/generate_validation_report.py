#!/usr/bin/env python3
"""
Generate validation report for cleaned JSONs.

Creates a 12-column report with per-file validation status, metadata
distribution, and a sample chunk. Outputs to Google Sheets + local CSV.

Prerequisites:
    Run validate_cleaned.py first to generate .tmp/validation_results.json

Usage:
    PYTHONPATH=. python tools/reporting/generate_validation_report.py
    PYTHONPATH=. python tools/reporting/generate_validation_report.py --csv-only

Output:
    - Google Sheets URL (printed to stdout)
    - .tmp/validation_report.csv (always generated)
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
VALIDATION_RESULTS = TMP_DIR / "validation_results.json"
CSV_OUTPUT = TMP_DIR / "validation_report.csv"

REPORT_HEADERS = [
    "File ID",
    "File Name",
    "File Type",
    "Total Chunks",
    "Chunking Method",
    "Metadata Method",
    "Validation Status",
    "Issues",
    "Country Distribution",
    "Bandera Distribution",
    "Fecha Range",
    "Sample Chunk",
]


def count_values(chunks, field):
    """Count occurrences of a metadata field across chunks. Returns sorted string."""
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
    """Extract fecha range from chunks."""
    fechas = set()
    for chunk in chunks:
        val = chunk.get("metadata", {}).get("fecha", "")
        if isinstance(val, list):
            fechas.update(v for v in val if v)
        elif val:
            fechas.add(val)
    if not fechas:
        return ""
    sorted_fechas = sorted(fechas)
    if len(sorted_fechas) == 1:
        return sorted_fechas[0]
    return f"{sorted_fechas[0]} to {sorted_fechas[-1]}"


def build_rows(validation_data):
    """Build report rows from validation results + cleaned JSONs."""
    per_file = validation_data.get("per_file_summary", {})
    issues_list = validation_data.get("issues", [])

    # Group issues by drive_id
    issues_by_file = {}
    for issue in issues_list:
        fid = issue["drive_id"]
        issues_by_file.setdefault(fid, []).append(issue)

    rows = []
    for fid, info in sorted(per_file.items(), key=lambda x: x[1].get("file_name", "")):
        # Load cleaned JSON for metadata distribution + sample chunk
        json_path = CLEANED_DIR / f"{fid}.json"
        chunks = []
        if json_path.exists():
            with open(json_path) as f:
                data = json.load(f)
            chunks = data.get("chunks", [])

        # Build issues string
        file_issues = issues_by_file.get(fid, [])
        issues_str = "; ".join(
            f"[{i['severity'].upper()}] {i['details']}" for i in file_issues[:5]
        )
        if len(file_issues) > 5:
            issues_str += f"; ... +{len(file_issues) - 5} more"

        # Sample chunk (first 300 chars of chunk[0])
        sample = ""
        if chunks:
            sample = chunks[0].get("text", "")[:300]

        rows.append([
            fid,
            info.get("file_name", ""),
            info.get("file_type", ""),
            info.get("total_chunks", 0),
            info.get("chunking_method", ""),
            info.get("metadata_method", ""),
            info.get("status", "").upper(),
            issues_str,
            count_values(chunks, "country"),
            count_values(chunks, "bandera"),
            fecha_range(chunks),
            sample,
        ])

    return rows


def build_summary(validation_data, rows):
    """Build summary tab data."""
    summary = validation_data.get("summary", {})
    per_file = validation_data.get("per_file_summary", {})

    # File type breakdown
    type_counts = Counter(v.get("file_type", "") for v in per_file.values())
    # Metadata method breakdown
    method_counts = Counter(v.get("metadata_method", "") for v in per_file.values())
    # Issue type breakdown
    issue_counts = Counter(i["check"] for i in validation_data.get("issues", []))

    summary_rows = [
        ["RAG Pipeline Validation Report"],
        [""],
        ["Metric", "Value"],
        ["Validated At", validation_data.get("validated_at", "")],
        ["Total Files", validation_data.get("total_files", 0)],
        ["Total Chunks", validation_data.get("total_chunks", 0)],
        ["PASS", summary.get("pass", 0)],
        ["WARNING", summary.get("warnings", 0)],
        ["ERROR", summary.get("errors", 0)],
        [""],
        ["File Type Breakdown"],
        ["Type", "Count"],
    ]
    for ft, count in type_counts.most_common():
        summary_rows.append([ft, count])

    summary_rows.extend([
        [""],
        ["Metadata Method Breakdown"],
        ["Method", "Count"],
    ])
    for method, count in method_counts.most_common():
        summary_rows.append([method or "(none)", count])

    if issue_counts:
        summary_rows.extend([
            [""],
            ["Issue Breakdown"],
            ["Issue Type", "Count"],
        ])
        for issue, count in issue_counts.most_common():
            summary_rows.append([issue, count])

    return summary_rows


def write_csv(rows):
    """Write report to local CSV."""
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(REPORT_HEADERS)
        writer.writerows(rows)
    print(f"CSV saved: {CSV_OUTPUT}")


def write_google_sheets(rows, summary_rows, title=None):
    """Write report to Google Sheets."""
    from tools.common.google_auth import authenticate_google_sheets, retry_with_backoff

    gc = authenticate_google_sheets()
    if not gc:
        print("ERROR: Could not authenticate with Google Sheets", file=sys.stderr)
        return None

    if not title:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = f"RAG Validation Report - {ts}"

    print(f"Creating Google Sheet: {title}")
    spreadsheet = gc.create(title)

    # Summary tab
    summary_ws = spreadsheet.sheet1
    summary_ws.update_title("Summary")
    retry_with_backoff(lambda: summary_ws.update(range_name="A1", values=summary_rows))

    # File Report tab
    report_ws = spreadsheet.add_worksheet(title="File Report", rows=200, cols=15)
    all_rows = [REPORT_HEADERS] + rows
    retry_with_backoff(lambda: report_ws.update(range_name="A1", values=all_rows))

    url = spreadsheet.url
    print(f"\nGoogle Sheet created: {url}")
    return url


def main():
    parser = argparse.ArgumentParser(description="Generate validation report")
    parser.add_argument("--csv-only", action="store_true",
                        help="Only generate CSV, skip Google Sheets")
    parser.add_argument("--title", default=None,
                        help="Google Sheets title")
    args = parser.parse_args()

    if not VALIDATION_RESULTS.exists():
        print(f"ERROR: {VALIDATION_RESULTS} not found. Run validate_cleaned.py first.",
              file=sys.stderr)
        sys.exit(1)

    with open(VALIDATION_RESULTS) as f:
        validation_data = json.load(f)

    print(f"Building report from {validation_data.get('total_files', 0)} files...")

    rows = build_rows(validation_data)
    summary_rows = build_summary(validation_data, rows)

    # Always write CSV
    write_csv(rows)

    # Write Google Sheets unless --csv-only
    if not args.csv_only:
        url = write_google_sheets(rows, summary_rows, args.title)
        if url:
            print(f"\n{url}")
    else:
        print("Skipping Google Sheets (--csv-only)")

    print(f"\nDone: {len(rows)} files in report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
