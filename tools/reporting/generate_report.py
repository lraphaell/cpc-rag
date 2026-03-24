#!/usr/bin/env python3
"""
Generate pipeline execution report in Google Sheets.

Reads ingestion_log.json and creates a summary sheet with:
- Summary tab: overall stats
- File Details tab: per-file breakdown
- Errors tab: failed files with troubleshooting

Usage:
    PYTHONPATH=. python tools/reporting/generate_report.py
    PYTHONPATH=. python tools/reporting/generate_report.py --log .tmp/ingestion_log.json

Output:
    Google Sheets URL printed to stdout
"""

import json
import sys
import argparse
from datetime import datetime, timezone

from tools.common.config import TMP_DIR
from tools.common.google_auth import authenticate_google_sheets, retry_with_backoff


def generate_report(log_path=None, sheet_title=None):
    """
    Generate a pipeline report in Google Sheets.

    Args:
        log_path: Path to ingestion_log.json
        sheet_title: Title for the Google Sheet (default: auto-generated)

    Returns:
        str: Google Sheets URL
    """
    if log_path is None:
        log_path = TMP_DIR / "ingestion_log.json"

    with open(log_path, "r") as f:
        log = json.load(f)

    gc = authenticate_google_sheets()
    if not gc:
        print("ERROR: Could not authenticate with Google Sheets", file=sys.stderr)
        sys.exit(1)

    if not sheet_title:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        sheet_title = f"RAG Pipeline Report - {ts}"

    print(f"Creating report: {sheet_title}")

    # Create spreadsheet
    spreadsheet = gc.create(sheet_title)

    # Summary tab (default Sheet1)
    summary_ws = spreadsheet.sheet1
    summary_ws.update_title("Summary")

    summary = log.get("summary", {})
    summary_data = [
        ["RAG Pipeline Execution Report"],
        [""],
        ["Metric", "Value"],
        ["Timestamp", log.get("ingested_at", "")],
        ["Namespace", log.get("namespace", "")],
        ["Total Changes", summary.get("total", 0)],
        ["Files Added", summary.get("added", 0)],
        ["Files Updated", summary.get("updated", 0)],
        ["Files Deleted", summary.get("deleted", 0)],
        ["Errors", summary.get("errors", 0)],
        ["Skipped", summary.get("skipped", 0)],
        ["Total Chunks Ingested", summary.get("total_chunks", 0)],
    ]
    summary_ws.update(range_name="A1", values=summary_data)

    # File Details tab
    details_ws = spreadsheet.add_worksheet(title="File Details", rows=200, cols=10)
    details_header = ["File Name", "Drive ID", "Status", "Chunks", "Modified Time", "Error"]
    details_rows = [details_header]

    for f in log.get("processed_files", []):
        details_rows.append([
            f.get("file_name", ""),
            f.get("drive_id", ""),
            f.get("status", ""),
            f.get("chunk_count", 0),
            f.get("modified_time", ""),
            f.get("error", f.get("reason", "")),
        ])

    for f in log.get("deleted_files", []):
        details_rows.append([
            f.get("name", ""),
            f.get("drive_id", ""),
            f.get("status", ""),
            0,
            "",
            "",
        ])

    details_ws.update(range_name="A1", values=details_rows)

    # Errors tab
    errors = [f for f in log.get("processed_files", []) if f.get("status") == "error"]
    if errors:
        errors_ws = spreadsheet.add_worksheet(title="Errors", rows=100, cols=5)
        errors_header = ["File Name", "Drive ID", "Error", "Suggestion"]
        errors_rows = [errors_header]

        for e in errors:
            suggestion = ""
            error_msg = e.get("error", "")
            if "parse" in error_msg.lower():
                suggestion = "Check file format or try different parser"
            elif "upsert" in error_msg.lower():
                suggestion = "Check Pinecone connection and API key"
            elif "download" in error_msg.lower():
                suggestion = "Check Drive permissions and file accessibility"

            errors_rows.append([
                e.get("file_name", ""),
                e.get("drive_id", ""),
                error_msg,
                suggestion,
            ])

        errors_ws.update(range_name="A1", values=errors_rows)

    url = spreadsheet.url
    print(f"\nReport created: {url}")
    return url


def main():
    parser = argparse.ArgumentParser(description="Generate pipeline report in Google Sheets")
    parser.add_argument("--log", default=str(TMP_DIR / "ingestion_log.json"),
                        help="Path to ingestion_log.json")
    parser.add_argument("--title", default=None,
                        help="Google Sheets title")
    args = parser.parse_args()

    url = generate_report(args.log, args.title)
    print(f"\n{url}")


if __name__ == "__main__":
    main()
