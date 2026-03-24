#!/usr/bin/env python3
"""
Generate per-file RAG strategy analysis report.

Analyzes each cleaned JSON and recommends chunking strategy, flags data quality
issues, and measures metadata completeness.

Usage:
    PYTHONPATH=. python tools/reporting/generate_strategy_analysis.py
    PYTHONPATH=. python tools/reporting/generate_strategy_analysis.py --csv-only
    PYTHONPATH=. python tools/reporting/generate_strategy_analysis.py --sheets

Output:
    .tmp/strategy_analysis.json (structured data)
    .tmp/strategy_analysis.csv  (tabular report)
    Google Sheets (optional, with --sheets)
"""

import csv
import json
import sys
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path

from tools.common.config import TMP_DIR
from tools.common.metadata_schema import VALID_COUNTRIES, VALID_TEAMS, VALID_BANDERAS

CLEANED_DIR = TMP_DIR / "cleaned"
JSON_OUTPUT = TMP_DIR / "strategy_analysis.json"
CSV_OUTPUT = TMP_DIR / "strategy_analysis.csv"

DIGIT_THRESHOLD = 0.12

HEADERS = [
    "File ID",
    "File Name",
    "File Type",
    "Detected Structure",
    "Current Chunking",
    "Recommended Chunking",
    "Chunk Count",
    "Avg Chunk Len",
    "Tabular Chunks",
    "Tabular %",
    "Metadata Completeness",
    "Country Fill %",
    "Bandera Fill %",
    "Fecha Fill %",
    "Quality Issues",
    "Action Needed",
]


def is_tabular(text):
    """Check if text is mostly numeric/tabular (>12% digits)."""
    if not text or len(text) < 50:
        return False
    return sum(1 for ch in text if ch.isdigit()) / len(text) > DIGIT_THRESHOLD


def analyze_file(json_path):
    """Analyze a single cleaned JSON file."""
    with open(json_path) as f:
        data = json.load(f)

    drive_id = data.get("drive_id", json_path.stem)
    file_name = data.get("file_name", "?")
    file_type = data.get("file_type", "?")
    chunking_method = data.get("chunking_method", "?")
    chunks = data.get("chunks", [])
    total_chunks = len(chunks)

    if total_chunks == 0:
        return {
            "drive_id": drive_id,
            "file_name": file_name,
            "file_type": file_type,
            "detected_structure": "empty",
            "current_chunking": chunking_method,
            "recommended_chunking": "skip",
            "chunk_count": 0,
            "avg_chunk_len": 0,
            "tabular_chunks": 0,
            "tabular_pct": 0,
            "metadata_completeness": 0,
            "country_fill": 0,
            "bandera_fill": 0,
            "fecha_fill": 0,
            "quality_issues": "empty file",
            "action_needed": "investigate",
        }

    # Chunk analysis
    texts = [c.get("text", "") for c in chunks]
    avg_len = sum(len(t) for t in texts) / total_chunks if total_chunks else 0
    tabular_count = sum(1 for t in texts if is_tabular(t))
    tabular_pct = (tabular_count / total_chunks * 100) if total_chunks else 0

    # Metadata analysis
    def field_fill_pct(field, defaults):
        filled = 0
        for c in chunks:
            val = c.get("metadata", {}).get(field, "")
            if isinstance(val, list):
                val = val[0] if val else ""
            if val and val not in defaults:
                filled += 1
        return (filled / total_chunks * 100) if total_chunks else 0

    country_fill = field_fill_pct("country", {"", "Corp"})
    bandera_fill = field_fill_pct("bandera", {"", "Otra"})
    fecha_fill = field_fill_pct("fecha", {""})
    team_fill = field_fill_pct("team", {"", "Genova"})
    metadata_completeness = (country_fill + bandera_fill + fecha_fill) / 3

    # Detect structure
    if tabular_pct > 80:
        structure = "tabular"
    elif tabular_pct > 30:
        structure = "mixed"
    elif file_type in ("pptx",):
        structure = "slides"
    elif file_type in ("docx", "doc"):
        structure = "document"
    elif file_type in ("pdf",):
        structure = "pdf"
    else:
        structure = "narrative"

    # Recommend chunking
    if structure == "tabular" and chunking_method != "summary_analytical":
        recommended = "summary_analytical"
    elif structure == "mixed" and chunking_method == "semantic":
        recommended = "hybrid (separate tabular)"
    elif structure == "slides":
        recommended = "structural"
    else:
        recommended = chunking_method  # keep current

    # Quality issues
    issues = []
    short_chunks = sum(1 for t in texts if len(t) < 50)
    long_chunks = sum(1 for t in texts if len(t) > 5000)
    seen = set()
    duplicates = 0
    for t in texts:
        key = t[:200].strip()
        if key in seen:
            duplicates += 1
        seen.add(key)

    if short_chunks > 0:
        issues.append(f"{short_chunks} short")
    if long_chunks > 0:
        issues.append(f"{long_chunks} long")
    if duplicates > 0:
        issues.append(f"{duplicates} dupes")
    if tabular_pct > 50 and chunking_method == "semantic":
        issues.append("tabular not summarized")
    if metadata_completeness < 20:
        issues.append("low metadata")

    # Action needed
    if recommended != chunking_method:
        action = f"rechunk → {recommended}"
    elif issues:
        action = "fix issues"
    else:
        action = "ready"

    return {
        "drive_id": drive_id,
        "file_name": file_name,
        "file_type": file_type,
        "detected_structure": structure,
        "current_chunking": chunking_method,
        "recommended_chunking": recommended,
        "chunk_count": total_chunks,
        "avg_chunk_len": round(avg_len),
        "tabular_chunks": tabular_count,
        "tabular_pct": round(tabular_pct, 1),
        "metadata_completeness": round(metadata_completeness, 1),
        "country_fill": round(country_fill, 1),
        "bandera_fill": round(bandera_fill, 1),
        "fecha_fill": round(fecha_fill, 1),
        "quality_issues": "; ".join(issues) if issues else "none",
        "action_needed": action,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate RAG strategy analysis report")
    parser.add_argument("--csv-only", action="store_true", help="Only output CSV, skip Google Sheets")
    parser.add_argument("--sheets", action="store_true", help="Also push to Google Sheets")
    args = parser.parse_args()

    if not CLEANED_DIR.exists():
        print("ERROR: No cleaned JSONs found.")
        sys.exit(1)

    json_files = sorted(CLEANED_DIR.glob("*.json"))
    print(f"Analyzing {len(json_files)} cleaned JSONs...")

    results = []
    for jp in json_files:
        try:
            result = analyze_file(jp)
            results.append(result)
        except Exception as e:
            print(f"  ERROR analyzing {jp.name}: {e}")

    # Summary stats
    total = len(results)
    by_structure = Counter(r["detected_structure"] for r in results)
    by_action = Counter(r["action_needed"] for r in results)
    need_rechunk = sum(1 for r in results if "rechunk" in r["action_needed"])
    total_chunks = sum(r["chunk_count"] for r in results)
    total_tabular = sum(r["tabular_chunks"] for r in results)
    avg_metadata = sum(r["metadata_completeness"] for r in results) / total if total else 0

    print(f"\n{'='*60}")
    print(f"STRATEGY ANALYSIS SUMMARY")
    print(f"{'='*60}")
    print(f"Files analyzed:         {total}")
    print(f"Total chunks:           {total_chunks}")
    print(f"Tabular chunks:         {total_tabular} ({total_tabular/total_chunks*100:.1f}%)" if total_chunks else "")
    print(f"Avg metadata complete:  {avg_metadata:.1f}%")
    print(f"\nStructure distribution: {dict(by_structure)}")
    print(f"Actions needed:         {dict(by_action)}")
    print(f"Need rechunking:        {need_rechunk} files")

    # Save JSON
    output = {
        "generated_at": datetime.now().isoformat(),
        "total_files": total,
        "total_chunks": total_chunks,
        "summary": {
            "by_structure": dict(by_structure),
            "by_action": dict(by_action),
            "need_rechunk": need_rechunk,
            "avg_metadata_completeness": round(avg_metadata, 1),
        },
        "files": results,
    }
    with open(JSON_OUTPUT, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nJSON saved to: {JSON_OUTPUT}")

    # Save CSV
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[k for k in results[0].keys()])
        writer.writeheader()
        writer.writerows(results)
    print(f"CSV saved to: {CSV_OUTPUT}")

    # Google Sheets (optional)
    if args.sheets:
        try:
            from tools.common.google_auth import authenticate_google_sheets
            print("\nPushing to Google Sheets...")
            # Implementation would go here using gspread
            print("(Google Sheets push not yet implemented)")
        except ImportError:
            print("Google Sheets auth not available")


if __name__ == "__main__":
    main()
