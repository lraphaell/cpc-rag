#!/usr/bin/env python3
"""
Auto-tag metadata ONLY for files that are clearly mono-country/mono-bandera.

Safe categories (all content is about ONE country + ONE bandera):
- Facturas: "Facturas Génova - Visa MLA" → all chunks are Visa + MLA
- Fee de bandera specific: "Fee de bandera Mastercard MLC" → all chunks are MC + MLC
- Revisiones mensuales: monthly reviews of a specific combo

NOT safe (multi-country/multi-bandera content inside):
- Monthly emails, Roadmaps, Documentos de proyecto, Workshops, SSOT, Evaluaciones, etc.
- These are left as "pending_agent_review" for chunk-by-chunk agent analysis.

Usage:
    PYTHONPATH=. python tools/cleanup/auto_tag_metadata.py
"""

import json
import glob
import re
import sys
from pathlib import Path
from tools.common.config import TMP_DIR

CLEANED_DIR = TMP_DIR / "cleaned"

# Patterns that indicate a file is SAFE for auto-tagging
# (content is about ONE specific country+bandera combo)
SAFE_PREFIXES = [
    r"^Facturas\b",              # Facturas Génova - Visa MLA, etc.
    r"^Fee de bandera\b",        # Fee de bandera files
    r"Revisión mensual fee",     # Monthly fee reviews
    r"^Visa MLM ACQ",            # Visa MLM invoice details
]

# Country detection
COUNTRY_MAP = {
    "MLA": [r"\bMLA\b"],
    "MLB": [r"\bMLB\b"],
    "MLM": [r"\bMLM\b"],
    "MLC": [r"\bMLC\b"],
    "MCO": [r"\bMCO\b"],
    "MLU": [r"\bMLU\b"],
}

# Bandera detection
BANDERA_MAP = {
    "Visa": [r"\bVISA\b", r"\bVisa\b"],
    "Mastercard": [r"\bMastercard\b", r"\bMASTERCARD\b", r"\bMaestro\b"],
    "Elo": [r"\bElo\b", r"\bELO\b"],
    "American Express": [r"\bAmex\b", r"\bAmerican Express\b"],
    "Cabal": [r"\bCabal\b"],
    "Hipercard": [r"\bHipercard\b"],
}

MONTH_TO_Q = {
    "ene": "Q1", "feb": "Q1", "mar": "Q1",
    "abr": "Q2", "may": "Q2", "jun": "Q2",
    "jul": "Q3", "ago": "Q3", "sep": "Q3",
    "oct": "Q4", "nov": "Q4", "dic": "Q4",
}


def is_safe_for_autotag(file_name):
    """Check if filename indicates mono-country/mono-bandera content."""
    for pattern in SAFE_PREFIXES:
        if re.search(pattern, file_name, re.IGNORECASE):
            return True
    return False


def detect_country(text):
    """Detect country code from text. Returns single string or None."""
    found = []
    for code, patterns in COUNTRY_MAP.items():
        for p in patterns:
            if re.search(p, text):
                found.append(code)
                break
    if len(found) == 1:
        return found[0]
    elif len(found) > 1:
        return found  # list
    return None


def detect_bandera(text):
    """Detect bandera from text. Returns single string or None."""
    found = []
    for name, patterns in BANDERA_MAP.items():
        for p in patterns:
            if re.search(p, text):
                found.append(name)
                break
    if len(found) == 1:
        return found[0]
    elif len(found) > 1:
        return found
    return None


def detect_fecha(text):
    """Detect fecha from filename."""
    # Q1-25, Q4/25, Q1_25
    m = re.search(r"Q([1-4])[-_/\s]?(?:20)?(\d{2})\b", text)
    if m:
        return f"20{m.group(2)}-Q{m.group(1)}"

    # 2025-Q1, 2025Q1
    m = re.search(r"(20\d{2})[-_]?Q([1-4])", text)
    if m:
        return f"{m.group(1)}-Q{m.group(2)}"

    # ene-25, nov-24
    m = re.search(r"\b(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[-_](\d{2})\b", text, re.IGNORECASE)
    if m:
        q = MONTH_TO_Q.get(m.group(1).lower(), "Q1")
        return f"20{m.group(2)}-{q}"

    # Year only: 2024, 2025, 2026
    m = re.search(r"\b(202[3-9])\b", text)
    if m:
        return m.group(1)

    return ""


def auto_tag():
    """Auto-tag only safe mono-country/bandera files."""
    files = sorted(CLEANED_DIR.glob("*.json"))

    auto_tagged = 0
    skipped = 0
    total_chunks_tagged = 0
    total_chunks_pending = 0

    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        if data.get("metadata_status") != "pending_agent_review":
            continue

        file_name = data.get("file_name", "")
        num_chunks = len(data.get("chunks", []))

        if not is_safe_for_autotag(file_name):
            skipped += 1
            total_chunks_pending += num_chunks
            continue

        # Extract metadata from filename
        country = detect_country(file_name)
        bandera = detect_bandera(file_name)
        fecha = detect_fecha(file_name)

        # Must have at least country or bandera to be useful
        if not country and not bandera:
            skipped += 1
            total_chunks_pending += num_chunks
            continue

        # Apply to all chunks
        for chunk in data.get("chunks", []):
            meta = chunk.get("metadata", {})
            if country:
                meta["country"] = country
            if bandera:
                meta["bandera"] = bandera
            meta["team"] = "Genova"  # All facturas/fees are Genova
            if fecha:
                meta["fecha"] = fecha

        data["metadata_status"] = "reviewed"
        data["metadata_method"] = "auto_safe_filename"

        with open(f, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

        total_chunks_tagged += num_chunks
        auto_tagged += 1
        c = country if isinstance(country, str) else "/".join(country) if country else "?"
        b = bandera if isinstance(bandera, str) else "/".join(bandera) if bandera else "?"
        print(f"  AUTO: {file_name[:65]:65s} → {c:5s} {b:12s} {fecha}")

    print(f"\n{'='*60}")
    print(f"Auto-tagged:     {auto_tagged} files ({total_chunks_tagged} chunks)")
    print(f"Pending agent:   {skipped} files ({total_chunks_pending} chunks)")
    print(f"{'='*60}")


if __name__ == "__main__":
    auto_tag()
