#!/usr/bin/env python3
"""
Fix invalid fecha format in cleaned JSONs.

Converts bare year values like "2025" to expanded quarter lists:
  "2025" -> ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]

This follows the rule in workflows/metadata_extraction.md:
  "Si pide '2025' -> ['2025-Q1', '2025-Q2', '2025-Q3', '2025-Q4']"

Idempotent: running multiple times produces the same result.

Usage:
    PYTHONPATH=. python tools/cleanup/fix_fecha_format.py
    PYTHONPATH=. python tools/cleanup/fix_fecha_format.py --dry-run
"""

import json
import re
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

from tools.common.config import TMP_DIR

CLEANED_DIR = TMP_DIR / "cleaned"
FECHA_VALID = re.compile(r"^\d{4}-Q[1-4]$")
BARE_YEAR = re.compile(r"^\d{4}$")


def expand_year(year_str):
    """Expand a bare year to all four quarters."""
    return [f"{year_str}-Q1", f"{year_str}-Q2", f"{year_str}-Q3", f"{year_str}-Q4"]


def fix_fecha_value(value):
    """
    Fix a single fecha value. Returns (fixed_value, was_changed).

    Handles: string, list, None, empty string.
    """
    if value is None or value == "":
        return value, False

    if isinstance(value, str):
        if FECHA_VALID.match(value):
            return value, False
        if BARE_YEAR.match(value):
            return expand_year(value), True
        # Comma-separated like "2025-Q1, 2025-Q2" -> convert to list
        if "," in value:
            parts = [v.strip() for v in value.split(",") if v.strip()]
            fixed_parts = []
            for p in parts:
                if BARE_YEAR.match(p):
                    fixed_parts.extend(expand_year(p))
                else:
                    fixed_parts.append(p)
            return fixed_parts, True  # always convert comma-string to list
        return value, False

    if isinstance(value, list):
        fixed = []
        changed = False
        for item in value:
            if isinstance(item, str) and BARE_YEAR.match(item):
                fixed.extend(expand_year(item))
                changed = True
            else:
                fixed.append(item)
        return fixed, changed

    return value, False


def main():
    parser = argparse.ArgumentParser(description="Fix invalid fecha format in cleaned JSONs")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    json_files = sorted(CLEANED_DIR.glob("*.json"))
    print(f"Scanning {len(json_files)} files...")

    total_fixes = 0
    files_fixed = 0

    for filepath in json_files:
        with open(filepath) as f:
            data = json.load(f)

        file_changed = False
        for chunk in data.get("chunks", []):
            meta = chunk.get("metadata", {})
            fecha = meta.get("fecha")
            fixed, changed = fix_fecha_value(fecha)
            if changed:
                total_fixes += 1
                idx = chunk.get("chunk_index", "?")
                print(f"  {data.get('file_name', '')[:60]}")
                print(f"    Chunk {idx}: '{fecha}' -> {fixed}")
                if not args.dry_run:
                    meta["fecha"] = fixed
                file_changed = True

        if file_changed:
            files_fixed += 1
            if not args.dry_run:
                with open(filepath, "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"\n{mode}: {total_fixes} chunks fixed in {files_fixed} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
