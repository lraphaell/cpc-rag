#!/usr/bin/env python3
"""
Validate all cleaned JSONs in .tmp/cleaned/ for structural integrity,
metadata correctness, and content quality.

Runs 13 checks across 3 severity levels:
  Level 1 (error):   Structural — required fields, chunk integrity
  Level 2 (error):   Metadata values — enums, fecha format
  Level 3 (warning): Content quality — text length, empty metadata, duplicates

Usage:
    PYTHONPATH=. python tools/reporting/validate_cleaned.py

Output:
    .tmp/validation_results.json
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from tools.common.config import TMP_DIR

CLEANED_DIR = TMP_DIR / "cleaned"

# ── Valid metadata values ────────────────────────────────────────────
VALID_COUNTRIES = {"MLA", "MLB", "MLM", "MLU", "MLC", "MCO", "Corp"}
VALID_TEAMS = {
    "Genova",
    "Relacionamiento con las banderas",
    "Negocio cross",
    "Bari",
    "Mejora Continua y Planning",
    "Scheme enablers",
    "Optimus",
    "X Countries",
}
VALID_BANDERAS = {
    "Visa", "Mastercard", "American Express", "Cabal",
    "Elo", "Hipercard", "Carnet", "Naranja", "Otra",
}
FECHA_REGEX = re.compile(r"^\d{4}-Q[1-4]$")

REQUIRED_TOP_FIELDS = [
    "drive_id", "file_name", "file_type", "source_url",
    "modified_time", "total_chunks", "chunking_method",
    "metadata_status", "chunks",
]
REQUIRED_META_KEYS = ["team", "country", "bandera", "fecha"]


def validate_enum(value, valid_set, field_name):
    """Validate a string or list value against valid set. Returns list of bad values."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in value if v not in valid_set]
    if isinstance(value, str):
        return [value] if value not in valid_set else []
    return [str(value)]


def validate_fecha(value):
    """Validate fecha format. Returns list of bad values."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in value if not FECHA_REGEX.match(str(v))]
    if isinstance(value, str):
        return [value] if not FECHA_REGEX.match(value) else []
    return [str(value)]


def validate_file(filepath):
    """Validate a single cleaned JSON. Returns (file_info, issues)."""
    issues = []

    try:
        with open(filepath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return None, [{"severity": "error", "check": "file_read", "details": str(e)}]

    drive_id = data.get("drive_id", filepath.stem)
    file_name = data.get("file_name", "")
    file_type = data.get("file_type", "")

    # ── Level 1: Structural ──────────────────────────────────────────
    for field in REQUIRED_TOP_FIELDS:
        if field not in data:
            issues.append({
                "severity": "error",
                "check": "missing_field",
                "details": f"Missing required field: {field}",
            })

    if data.get("metadata_status") != "reviewed":
        issues.append({
            "severity": "error",
            "check": "metadata_status",
            "details": f"metadata_status='{data.get('metadata_status')}', expected 'reviewed'",
        })

    chunks = data.get("chunks", [])
    declared = data.get("total_chunks", -1)
    if declared != len(chunks):
        issues.append({
            "severity": "error",
            "check": "chunk_count_mismatch",
            "details": f"total_chunks={declared} but actual={len(chunks)}",
        })

    for i, chunk in enumerate(chunks):
        text = chunk.get("text", "")
        if not text or len(text) < 10:
            issues.append({
                "severity": "error",
                "check": "empty_chunk_text",
                "details": f"Chunk {i}: text is empty or too short ({len(text)} chars)",
            })

        meta = chunk.get("metadata")
        if not isinstance(meta, dict):
            issues.append({
                "severity": "error",
                "check": "missing_metadata_dict",
                "details": f"Chunk {i}: metadata is not a dict",
            })
        else:
            for key in REQUIRED_META_KEYS:
                if key not in meta:
                    issues.append({
                        "severity": "error",
                        "check": "missing_metadata_key",
                        "details": f"Chunk {i}: missing metadata key '{key}'",
                    })

        expected_idx = i
        actual_idx = chunk.get("chunk_index", -1)
        if actual_idx != expected_idx:
            issues.append({
                "severity": "error",
                "check": "chunk_index_sequence",
                "details": f"Chunk {i}: chunk_index={actual_idx}, expected {expected_idx}",
            })

    # ── Level 2: Metadata values ─────────────────────────────────────
    for i, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})

        bad = validate_enum(meta.get("country"), VALID_COUNTRIES, "country")
        for v in bad:
            issues.append({
                "severity": "error",
                "check": "invalid_country",
                "details": f"Chunk {i}: country='{v}' not in valid set",
            })

        bad = validate_enum(meta.get("team"), VALID_TEAMS, "team")
        for v in bad:
            issues.append({
                "severity": "error",
                "check": "invalid_team",
                "details": f"Chunk {i}: team='{v}' not in valid set",
            })

        bad = validate_enum(meta.get("bandera"), VALID_BANDERAS, "bandera")
        for v in bad:
            issues.append({
                "severity": "error",
                "check": "invalid_bandera",
                "details": f"Chunk {i}: bandera='{v}' not in valid set",
            })

        bad = validate_fecha(meta.get("fecha"))
        for v in bad:
            issues.append({
                "severity": "error",
                "check": "invalid_fecha",
                "details": f"Chunk {i}: fecha='{v}' does not match YYYY-QN format",
            })

    # ── Level 3: Content quality (warnings) ──────────────────────────
    texts = []
    for i, chunk in enumerate(chunks):
        text = chunk.get("text", "")
        texts.append(text)

        if 0 < len(text) < 50:
            issues.append({
                "severity": "warning",
                "check": "short_chunk",
                "details": f"Chunk {i}: only {len(text)} chars",
            })
        if len(text) > 5000:
            issues.append({
                "severity": "warning",
                "check": "long_chunk",
                "details": f"Chunk {i}: {len(text)} chars (>5000)",
            })

        meta = chunk.get("metadata", {})
        country = meta.get("country", "")
        bandera = meta.get("bandera", "")
        fecha = meta.get("fecha", "")
        if (not country or country == "Corp") and (not bandera or bandera == "Otra") and not fecha:
            issues.append({
                "severity": "warning",
                "check": "all_default_metadata",
                "details": f"Chunk {i}: all metadata fields are empty/default",
            })

    # Check for duplicate chunk text within file
    text_counts = Counter(texts)
    for text_val, count in text_counts.items():
        if count > 1 and len(text_val) > 20:
            issues.append({
                "severity": "warning",
                "check": "duplicate_chunk_text",
                "details": f"{count} chunks share identical text ({len(text_val)} chars)",
            })

    file_info = {
        "drive_id": drive_id,
        "file_name": file_name,
        "file_type": file_type,
        "total_chunks": len(chunks),
        "chunking_method": data.get("chunking_method", ""),
        "metadata_method": data.get("metadata_method", ""),
    }

    return file_info, issues


def main():
    if not CLEANED_DIR.exists():
        print(f"ERROR: {CLEANED_DIR} does not exist", file=sys.stderr)
        sys.exit(1)

    json_files = sorted(CLEANED_DIR.glob("*.json"))
    if not json_files:
        print(f"ERROR: No JSON files found in {CLEANED_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating {len(json_files)} cleaned JSONs...")

    all_issues = []
    per_file = {}
    total_chunks = 0
    pass_count = 0
    warning_count = 0
    error_count = 0

    for filepath in json_files:
        file_info, issues = validate_file(filepath)
        fid = file_info["drive_id"] if file_info else filepath.stem

        has_errors = any(i["severity"] == "error" for i in issues)
        has_warnings = any(i["severity"] == "warning" for i in issues)

        if has_errors:
            status = "error"
            error_count += 1
        elif has_warnings:
            status = "warning"
            warning_count += 1
        else:
            status = "pass"
            pass_count += 1

        if file_info:
            total_chunks += file_info["total_chunks"]

        per_file[fid] = {
            "file_name": file_info["file_name"] if file_info else "",
            "file_type": file_info["file_type"] if file_info else "",
            "total_chunks": file_info["total_chunks"] if file_info else 0,
            "chunking_method": file_info["chunking_method"] if file_info else "",
            "metadata_method": file_info["metadata_method"] if file_info else "",
            "issues_count": len(issues),
            "status": status,
        }

        for issue in issues:
            all_issues.append({
                "drive_id": fid,
                "file_name": file_info["file_name"] if file_info else "",
                **issue,
            })

    results = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "total_files": len(json_files),
        "total_chunks": total_chunks,
        "summary": {
            "pass": pass_count,
            "warnings": warning_count,
            "errors": error_count,
        },
        "issues": all_issues,
        "per_file_summary": per_file,
    }

    output_path = TMP_DIR / "validation_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\nResults saved to {output_path}")
    print(f"  Files:    {len(json_files)}")
    print(f"  Chunks:   {total_chunks}")
    print(f"  PASS:     {pass_count}")
    print(f"  WARNING:  {warning_count}")
    print(f"  ERROR:    {error_count}")
    print(f"  Issues:   {len(all_issues)}")

    if all_issues:
        print("\nTop issues:")
        check_counts = Counter(i["check"] for i in all_issues)
        for check, count in check_counts.most_common(10):
            severity = next(i["severity"] for i in all_issues if i["check"] == check)
            print(f"  [{severity.upper()}] {check}: {count}")

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
