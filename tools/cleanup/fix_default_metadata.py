#!/usr/bin/env python3
"""
Enrich chunks that have all-default metadata by inferring values
from the file name and chunk text content.

Only updates fields where inference is confident. Keeps defaults
when ambiguous (precision > coverage).

Rules follow workflows/metadata_extraction.md.

Usage:
    PYTHONPATH=. python tools/cleanup/fix_default_metadata.py
    PYTHONPATH=. python tools/cleanup/fix_default_metadata.py --dry-run
"""

import json
import re
import sys
import argparse
from collections import Counter
from pathlib import Path

from tools.common.config import TMP_DIR

CLEANED_DIR = TMP_DIR / "cleaned"

# ── Detection patterns ───────────────────────────────────────────────

# Country: code -> pattern (case-insensitive)
COUNTRY_PATTERNS = {
    "MLA": re.compile(r"\bMLA\b|Argentina", re.IGNORECASE),
    "MLB": re.compile(r"\bMLB\b|Brasil|Brazil", re.IGNORECASE),
    "MLM": re.compile(r"\bMLM\b|M[eé]xico|PROSA", re.IGNORECASE),
    "MLU": re.compile(r"\bMLU\b|Uruguay", re.IGNORECASE),
    "MLC": re.compile(r"\bMLC\b|Chile", re.IGNORECASE),
    "MCO": re.compile(r"\bMCO\b|Colombia", re.IGNORECASE),
}

# Bandera: name -> pattern
BANDERA_PATTERNS = {
    "Visa": re.compile(r"\bVisa\b|VISA\b", re.IGNORECASE),
    "Mastercard": re.compile(r"\bMastercard\b|\bMC\b(?!\s*&)|Mastercard", re.IGNORECASE),
    "American Express": re.compile(r"\bAmex\b|American\s*Express", re.IGNORECASE),
    "Elo": re.compile(r"\bElo\b|\bELO\b"),
    "Cabal": re.compile(r"\bCabal\b", re.IGNORECASE),
    "Hipercard": re.compile(r"\bHipercard\b", re.IGNORECASE),
    "Carnet": re.compile(r"\bCarnet\b", re.IGNORECASE),
    "Naranja": re.compile(r"\bNaranja\b", re.IGNORECASE),
}

# Fecha: year detection
YEAR_PATTERN = re.compile(r"\b(202[3-9]|203[0-9])\b")
QUARTER_PATTERN = re.compile(r"\b(Q[1-4])\s*(202[3-9]|203[0-9])\b|\b(202[3-9]|203[0-9])\s*(Q[1-4])\b", re.IGNORECASE)
HALF_PATTERN = re.compile(r"\b(H[12])\s*(202[3-9]|203[0-9])\b", re.IGNORECASE)
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
MONTH_PATTERN = re.compile(
    r"\b(" + "|".join(MONTH_MAP.keys()) + r")\s*(?:de\s+)?(202[3-9]|203[0-9])\b",
    re.IGNORECASE,
)

# Team patterns
TEAM_PATTERNS = {
    "Optimus": re.compile(r"\bOptimus\b", re.IGNORECASE),
    "Bari": re.compile(r"\bBari\b", re.IGNORECASE),
    "Scheme enablers": re.compile(r"\bScheme\s*enablers?\b", re.IGNORECASE),
    "Mejora Continua y Planning": re.compile(r"\bMejora\s*Continua\b|\bPlanning\b", re.IGNORECASE),
    "Relacionamiento con las banderas": re.compile(r"\bRelacionamiento\b", re.IGNORECASE),
    "Negocio cross": re.compile(r"\bNegocio\s*cross\b", re.IGNORECASE),
    "X Countries": re.compile(r"\bX\s*Countries\b", re.IGNORECASE),
}


def is_default_metadata(meta):
    """Check if all metadata fields are empty/default."""
    country = meta.get("country", "")
    bandera = meta.get("bandera", "")
    fecha = meta.get("fecha", "")
    return (not country or country == "Corp") and (not bandera or bandera == "Otra") and not fecha


def detect_countries(text):
    """Detect country codes from text."""
    found = []
    for code, pattern in COUNTRY_PATTERNS.items():
        if pattern.search(text):
            found.append(code)
    return found


def detect_banderas(text):
    """Detect card brands from text."""
    found = []
    for name, pattern in BANDERA_PATTERNS.items():
        if pattern.search(text):
            found.append(name)
    return found


def detect_fechas(text):
    """Detect temporal references from text."""
    fechas = set()

    # Explicit quarters: "Q1 2025" or "2025 Q1"
    for m in QUARTER_PATTERN.finditer(text):
        q = m.group(1) or m.group(4)
        year = m.group(2) or m.group(3)
        fechas.add(f"{year}-{q.upper()}")

    # Half years: "H1 2025"
    for m in HALF_PATTERN.finditer(text):
        half = m.group(1).upper()
        year = m.group(2)
        if half == "H1":
            fechas.add(f"{year}-Q1")
            fechas.add(f"{year}-Q2")
        else:
            fechas.add(f"{year}-Q3")
            fechas.add(f"{year}-Q4")

    # Month + year: "noviembre 2025"
    for m in MONTH_PATTERN.finditer(text):
        month = m.group(1).lower()
        year = m.group(2)
        q = MONTH_MAP.get(month)
        if q:
            fechas.add(f"{year}-{q}")

    return sorted(fechas)


def detect_team(text):
    """Detect team from text. Returns team name or None."""
    for team, pattern in TEAM_PATTERNS.items():
        if pattern.search(text):
            return team
    return None


def infer_metadata(file_name, chunk_text, other_chunks_meta=None):
    """
    Infer metadata from file name + chunk text.
    Returns dict of fields to update (only non-default values).
    """
    # Combine file name and text for broader detection
    combined = f"{file_name} {chunk_text}"
    updates = {}

    # Country
    countries = detect_countries(combined)
    if countries:
        updates["country"] = countries if len(countries) > 1 else countries[0]

    # Bandera
    banderas = detect_banderas(combined)
    if banderas:
        updates["bandera"] = banderas if len(banderas) > 1 else banderas[0]

    # Fecha
    fechas = detect_fechas(combined)
    if fechas:
        updates["fecha"] = fechas if len(fechas) > 1 else fechas[0]

    # Team (only override if explicitly detected, otherwise keep Genova default)
    team = detect_team(combined)
    if team:
        updates["team"] = team

    return updates


def _is_empty_or_default(value, field):
    """Check if a metadata field value is empty or default."""
    defaults = {"team": ("", "Genova"), "country": ("", "Corp"), "bandera": ("", "Otra"), "fecha": ("",)}
    if isinstance(value, list):
        value = value[0] if value else ""
    return value in defaults.get(field, ("",))


def fix_file(filepath, dry_run=False):
    """Enrich metadata in a single file. Returns count of chunks updated."""
    with open(filepath) as f:
        data = json.load(f)

    file_name = data.get("file_name", "")
    chunks = data.get("chunks", [])
    updated = 0

    # Collect metadata from non-default chunks as context
    other_meta = [c.get("metadata", {}) for c in chunks if not is_default_metadata(c.get("metadata", {}))]

    for chunk in chunks:
        meta = chunk.get("metadata", {})

        # Pass 1: All-default chunks — infer everything
        if is_default_metadata(meta):
            updates = infer_metadata(file_name, chunk.get("text", ""), other_meta)
            if updates:
                updated += 1
                if not dry_run:
                    for key, val in updates.items():
                        meta[key] = val
            continue

        # Pass 2: Partial metadata — fill individual empty/default fields
        updates = infer_metadata(file_name, chunk.get("text", ""), other_meta)
        if not updates:
            continue

        chunk_changed = False
        for field in ("country", "bandera", "fecha", "team"):
            if field not in updates:
                continue
            current = meta.get(field, "")
            if _is_empty_or_default(current, field):
                if not dry_run:
                    meta[field] = updates[field]
                chunk_changed = True

        if chunk_changed:
            updated += 1

    # Also set pending_agent_review to reviewed after enrichment
    if updated > 0 and not dry_run:
        if data.get("metadata_status") == "pending_agent_review":
            data["metadata_status"] = "reviewed"
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    return updated


def main():
    parser = argparse.ArgumentParser(description="Enrich default metadata from content")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    json_files = sorted(CLEANED_DIR.glob("*.json"))
    print(f"Scanning {len(json_files)} files for default metadata...")

    total_updated = 0
    files_fixed = 0

    for filepath in json_files:
        count = fix_file(filepath, args.dry_run)
        if count > 0:
            with open(filepath) as f:
                data = json.load(f)
            name = data.get("file_name", filepath.stem)[:60]
            print(f"  {name}: enriched {count} chunks")
            total_updated += count
            files_fixed += 1

    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"\n{mode}: {total_updated} chunks enriched in {files_fixed} files")


if __name__ == "__main__":
    main()
