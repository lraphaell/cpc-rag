#!/usr/bin/env python3
"""
Propagate metadata across chunks within the same file using two strategies:

1. Filename extraction (enhanced): detects team/fecha/country/bandera from
   the file name with broader patterns (short years, dash separators, etc.)
2. Consensus propagation: if non-default chunks in the same file agree on a
   value, apply it to chunks that still have empty/default values.

This script runs AFTER fix_default_metadata.py (which does per-chunk
per-text inference). It fills the remaining gaps by looking at the file
level and sibling chunks.

Usage:
    PYTHONPATH=. python tools/cleanup/fix_metadata_inheritance.py
    PYTHONPATH=. python tools/cleanup/fix_metadata_inheritance.py --dry-run
    PYTHONPATH=. python tools/cleanup/fix_metadata_inheritance.py --file "filename.json"
"""

import json
import re
import sys
import argparse
from collections import Counter, defaultdict
from pathlib import Path

from tools.common.config import TMP_DIR

CLEANED_DIR = TMP_DIR / "cleaned"

# ── Detection patterns (imported from fix_default_metadata, extended) ────────

COUNTRY_PATTERNS = {
    "MLA": re.compile(r"\bMLA\b|Argentina", re.IGNORECASE),
    "MLB": re.compile(r"\bMLB\b|Brasil|Brazil", re.IGNORECASE),
    "MLM": re.compile(r"\bMLM\b|M[eé]xico|PROSA", re.IGNORECASE),
    "MLU": re.compile(r"\bMLU\b|Uruguay", re.IGNORECASE),
    "MLC": re.compile(r"\bMLC\b|Chile", re.IGNORECASE),
    "MCO": re.compile(r"\bMCO\b|Colombia", re.IGNORECASE),
}

BANDERA_PATTERNS = {
    "Visa": re.compile(r"\bVisa\b|VISA\b", re.IGNORECASE),
    "Mastercard": re.compile(r"\bMastercard\b|\bMC\b(?!\s*&)", re.IGNORECASE),
    "American Express": re.compile(r"\bAmex\b|American\s*Express", re.IGNORECASE),
    "Elo": re.compile(r"\bElo\b|\bELO\b"),
    "Cabal": re.compile(r"\bCabal\b", re.IGNORECASE),
    "Hipercard": re.compile(r"\bHipercard\b", re.IGNORECASE),
    "Carnet": re.compile(r"\bCarnet\b", re.IGNORECASE),
    "Naranja": re.compile(r"\bNaranja\b", re.IGNORECASE),
}

TEAM_PATTERNS = {
    "Optimus": re.compile(r"\bOptimus\b", re.IGNORECASE),
    "Bari": re.compile(r"\bBari\b", re.IGNORECASE),
    "Scheme enablers": re.compile(r"\bScheme\s*enablers?\b", re.IGNORECASE),
    "Mejora Continua y Planning": re.compile(r"\bMejora\s*Continua\b|\bPlanning\b", re.IGNORECASE),
    "Relacionamiento con las banderas": re.compile(r"\bRelacionamiento\b", re.IGNORECASE),
    "Negocio cross": re.compile(r"\bNegocio\s*cross\b", re.IGNORECASE),
    "X Countries": re.compile(r"\bX\s*Countries\b", re.IGNORECASE),
}

# Month name → quarter mapping
MONTH_MAP = {
    "enero": "Q1", "febrero": "Q1", "marzo": "Q1",
    "abril": "Q2", "mayo": "Q2", "junio": "Q2",
    "julio": "Q3", "agosto": "Q3", "septiembre": "Q3", "setiembre": "Q3",
    "octubre": "Q4", "noviembre": "Q4", "diciembre": "Q4",
    "january": "Q1", "february": "Q1", "march": "Q1",
    "april": "Q2", "may": "Q2", "june": "Q2",
    "july": "Q3", "august": "Q3", "september": "Q3",
    "october": "Q4", "november": "Q4", "december": "Q4",
    "jan": "Q1", "feb": "Q1", "mar": "Q1",
    "apr": "Q2", "jun": "Q2",
    "jul": "Q3", "aug": "Q3", "sep": "Q3",
    "oct": "Q4", "nov": "Q4", "dec": "Q4",
}
_MONTH_NAMES = "|".join(MONTH_MAP.keys())

# Standard: "Q3 2025" or "2025 Q3" (space-separated)
QUARTER_PATTERN = re.compile(
    r"\b(Q[1-4])\s+(202[3-9]|203[0-9])\b|\b(202[3-9]|203[0-9])\s+(Q[1-4])\b",
    re.IGNORECASE,
)
# Extended: "2025-Q3", "2025_Q3", "Q3-2025", "Q3_2025"
QUARTER_DASH_PATTERN = re.compile(
    r"\b(Q[1-4])[-_](202[3-9]|203[0-9])\b|\b(202[3-9]|203[0-9])[-_](Q[1-4])\b",
    re.IGNORECASE,
)
# Half year: "H1 2025"
HALF_PATTERN = re.compile(r"\b(H[12])[\s\-_]*(202[3-9]|203[0-9])\b", re.IGNORECASE)
# Month + full year: "noviembre 2025", "oct 2025"
MONTH_YEAR_FULL = re.compile(
    r"\b(" + _MONTH_NAMES + r")\s*(?:de\s+)?(202[3-9]|203[0-9])\b",
    re.IGNORECASE,
)
# Month + short year: "oct-25", "oct_25", "oct 25"
MONTH_YEAR_SHORT = re.compile(
    r"\b(" + _MONTH_NAMES + r")[-_\s](2[4-9])\b",
    re.IGNORECASE,
)
# Bare year in filename (only use when no other date info found)
BARE_YEAR_PATTERN = re.compile(r"\b(202[3-9]|203[0-9])\b")


def detect_fechas_enhanced(text: str) -> list:
    """
    Extract fecha values from text with extended patterns.
    Handles standard, dash-separated, short-year, and month-name formats.
    Returns sorted list of YYYY-QN strings.
    """
    fechas = set()

    # Standard: "Q3 2025" or "2025 Q3"
    for m in QUARTER_PATTERN.finditer(text):
        q = (m.group(1) or m.group(4)).upper()
        year = m.group(2) or m.group(3)
        fechas.add(f"{year}-{q}")

    # Dash/underscore: "2025-Q3" or "Q3_2025"
    for m in QUARTER_DASH_PATTERN.finditer(text):
        q = (m.group(1) or m.group(4)).upper()
        year = m.group(2) or m.group(3)
        fechas.add(f"{year}-{q}")

    # Half year: "H1 2025" → Q1+Q2
    for m in HALF_PATTERN.finditer(text):
        half = m.group(1).upper()
        year = m.group(2)
        if half == "H1":
            fechas.update([f"{year}-Q1", f"{year}-Q2"])
        else:
            fechas.update([f"{year}-Q3", f"{year}-Q4"])

    # Month + full year
    for m in MONTH_YEAR_FULL.finditer(text):
        month = m.group(1).lower()
        year = m.group(2)
        q = MONTH_MAP.get(month)
        if q:
            fechas.add(f"{year}-{q}")

    # Month + short year ("oct-25" → 2025-Q4)
    for m in MONTH_YEAR_SHORT.finditer(text):
        month = m.group(1).lower()
        short_year = m.group(2)
        year = f"20{short_year}"
        q = MONTH_MAP.get(month)
        if q:
            fechas.add(f"{year}-{q}")

    return sorted(fechas)


def detect_team_from_filename(file_name: str) -> str | None:
    """Detect team from file name only."""
    for team, pattern in TEAM_PATTERNS.items():
        if pattern.search(file_name):
            return team
    return None


def detect_country_from_filename(file_name: str) -> list:
    found = []
    for code, pattern in COUNTRY_PATTERNS.items():
        if pattern.search(file_name):
            found.append(code)
    return found


def detect_bandera_from_filename(file_name: str) -> list:
    found = []
    for name, pattern in BANDERA_PATTERNS.items():
        if pattern.search(file_name):
            found.append(name)
    return found


def _scalar(val):
    """Return scalar representation of a metadata value."""
    if isinstance(val, list):
        return val[0] if val else ""
    return val or ""


def _is_empty_or_default(val, field):
    defaults = {
        "team": ("", "Genova"),
        "country": ("", "Corp"),
        "bandera": ("", "Otra"),
        "fecha": ("",),
    }
    return _scalar(val) in defaults.get(field, ("",))


def build_consensus(chunks: list) -> dict:
    """
    Build per-field consensus from non-default chunk metadata.
    Returns dict of {field: value_or_list} for fields with clear consensus.
    """
    counters = {f: Counter() for f in ("team", "country", "bandera", "fecha")}

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        for field in counters:
            val = meta.get(field, "")
            if isinstance(val, list):
                for v in val:
                    if v and not _is_empty_or_default(v, field):
                        counters[field][v] += 1
            else:
                if val and not _is_empty_or_default(val, field):
                    counters[field][val] += 1

    consensus = {}
    for field, counter in counters.items():
        if not counter:
            continue
        top = counter.most_common(3)
        if len(top) == 1:
            consensus[field] = top[0][0]
        else:
            # Multiple values: keep top-3 as list (e.g. multiple countries)
            consensus[field] = [v for v, _ in top]

    return consensus


def fix_file(filepath: Path, dry_run: bool = False) -> dict:
    """
    Apply metadata inheritance to a single cleaned JSON.
    Returns stats dict.
    """
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    file_name = data.get("file_name", "")
    chunks = data.get("chunks", [])

    if not chunks:
        return {"file": file_name, "updated": 0, "skipped": "no chunks"}

    # ── Strategy 1: extract from filename (enhanced patterns) ─────────────
    filename_team = detect_team_from_filename(file_name)
    filename_fecha = detect_fechas_enhanced(file_name)
    filename_country = detect_country_from_filename(file_name)
    filename_bandera = detect_bandera_from_filename(file_name)

    # ── Strategy 2: consensus from sibling chunks ──────────────────────────
    consensus = build_consensus(chunks)

    # Merge: consensus takes priority over filename (more specific)
    inherited = {}
    for field in ("team", "country", "bandera", "fecha"):
        if field in consensus:
            inherited[field] = consensus[field]
        elif field == "team" and filename_team:
            inherited["team"] = filename_team
        elif field == "fecha" and filename_fecha:
            inherited["fecha"] = filename_fecha[0] if len(filename_fecha) == 1 else filename_fecha
        elif field == "country" and filename_country:
            inherited["country"] = filename_country[0] if len(filename_country) == 1 else filename_country
        elif field == "bandera" and filename_bandera:
            inherited["bandera"] = filename_bandera[0] if len(filename_bandera) == 1 else filename_bandera

    if not inherited:
        return {"file": file_name[:60], "updated": 0, "skipped": "no inheritance signals"}

    # ── Apply to chunks with empty/default values ──────────────────────────
    updated_count = 0
    field_updates = defaultdict(int)

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        chunk_changed = False

        for field, value in inherited.items():
            current = meta.get(field, "")
            if _is_empty_or_default(current, field):
                if not dry_run:
                    meta[field] = value
                chunk_changed = True
                field_updates[field] += 1

        if chunk_changed:
            updated_count += 1

    if updated_count > 0 and not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    return {
        "file": file_name[:60],
        "updated": updated_count,
        "total": len(chunks),
        "inherited": inherited,
        "field_updates": dict(field_updates),
    }


def main():
    parser = argparse.ArgumentParser(description="Propagate metadata across chunks by inheritance")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument("--file", help="Process a single file (by name pattern)")
    args = parser.parse_args()

    if args.file:
        matches = list(CLEANED_DIR.glob(f"*{args.file}*"))
        if not matches:
            print(f"No files matching: {args.file}")
            sys.exit(1)
        json_files = matches
    else:
        json_files = sorted(CLEANED_DIR.glob("*.json"))

    mode = "DRY RUN" if args.dry_run else "APPLYING"
    print(f"{mode}: Scanning {len(json_files)} files for metadata inheritance...\n")

    total_files_updated = 0
    total_chunks_updated = 0
    field_totals = defaultdict(int)

    for filepath in json_files:
        result = fix_file(filepath, args.dry_run)
        if result["updated"] > 0:
            total_files_updated += 1
            total_chunks_updated += result["updated"]
            for field, count in result.get("field_updates", {}).items():
                field_totals[field] += count
            inherited_summary = {k: (v if not isinstance(v, list) else v[:2]) for k, v in result["inherited"].items()}
            print(f"  {result['file'][:55]}")
            print(f"    → {result['updated']}/{result['total']} chunks | inherited: {inherited_summary}")

    print(f"\n{'─'*60}")
    print(f"{mode}: {total_chunks_updated} chunks updated in {total_files_updated} files")
    if field_totals:
        print("Field breakdown:")
        for field, count in sorted(field_totals.items()):
            print(f"  {field}: +{count} chunks filled")


if __name__ == "__main__":
    main()
