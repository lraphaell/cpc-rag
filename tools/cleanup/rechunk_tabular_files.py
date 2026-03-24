#!/usr/bin/env python3
"""
Rechunk tabular files: replace massive raw-data chunks with analytical summaries.

For xlsx files with semantic chunking that produced thousands of tabular chunks
(>12% digit ratio), this script:
1. Identifies target files (xlsx + semantic + >50% tabular OR >100 chunks)
2. Generates analytical summaries from chunk text (without re-parsing the original file)
3. Preserves metadata from original chunks
4. Replaces the cleaned JSON with a compact version

Usage:
    PYTHONPATH=. python tools/cleanup/rechunk_tabular_files.py --dry-run
    PYTHONPATH=. python tools/cleanup/rechunk_tabular_files.py
    PYTHONPATH=. python tools/cleanup/rechunk_tabular_files.py --min-chunks 50
"""

import json
import os
import sys
import re
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tools.common.config import TMP_DIR

CLEANED_DIR = TMP_DIR / "cleaned"
DIGIT_THRESHOLD = 0.12


def is_tabular(text):
    """Check if text is mostly numeric/tabular."""
    if not text or len(text) < 50:
        return False
    return sum(1 for ch in text if ch.isdigit()) / len(text) > DIGIT_THRESHOLD


def extract_key_info_from_chunks(chunks, file_name):
    """
    Extract analytical summary from tabular chunk texts.

    Instead of re-parsing the original file (slow for 40MB+ Excel),
    we analyze the chunk texts to build a useful summary.
    """
    all_text = "\n".join(c.get("text", "")[:2000] for c in chunks[:50])  # Sample first 50 chunks

    # Extract patterns from text
    countries = set()
    banderas = set()
    dates = set()
    numbers = []
    column_names = set()
    sheet_names = set()

    country_patterns = {
        'MLA': r'\bMLA\b', 'MLB': r'\bMLB\b', 'MLM': r'\bMLM\b',
        'MLU': r'\bMLU\b', 'MLC': r'\bMLC\b', 'MCO': r'\bMCO\b',
        'Argentina': r'\bArgentina\b', 'Brasil': r'\bBrasil\b',
        'México': r'\bM[eé]xico\b', 'Uruguay': r'\bUruguay\b',
        'Chile': r'\bChile\b', 'Colombia': r'\bColombia\b',
    }

    bandera_patterns = {
        'Visa': r'\bVisa\b', 'Mastercard': r'\bMastercard\b',
        'Maestro': r'\bMaestro\b', 'American Express': r'\bAmex|American Express\b',
        'Cabal': r'\bCabal\b', 'Elo': r'\bElo\b',
    }

    for name, pattern in country_patterns.items():
        if re.search(pattern, all_text, re.IGNORECASE):
            countries.add(name)

    for name, pattern in bandera_patterns.items():
        if re.search(pattern, all_text, re.IGNORECASE):
            banderas.add(name)

    # Extract year/quarter references
    for m in re.finditer(r'20[12]\d[-_]?Q[1-4]', all_text):
        dates.add(m.group())
    for m in re.finditer(r'\b20[12]\d\b', all_text):
        dates.add(m.group())

    # Also check from filename
    for name, pattern in country_patterns.items():
        if re.search(pattern, file_name, re.IGNORECASE):
            countries.add(name)
    for name, pattern in bandera_patterns.items():
        if re.search(pattern, file_name, re.IGNORECASE):
            banderas.add(name)

    # Build summary
    total_chunks = len(chunks)
    tabular_count = sum(1 for c in chunks if is_tabular(c.get("text", "")))
    narrative_count = total_chunks - tabular_count

    # Get sample of first non-trivial text for context
    sample_texts = []
    for c in chunks[:10]:
        text = c.get("text", "").strip()
        if text and len(text) > 20:
            sample_texts.append(text[:300])

    summary_parts = [
        f"Archivo: {file_name}",
        f"Tipo: Planilla Excel con datos tabulares",
        f"Chunks originales: {total_chunks} ({tabular_count} tabulares, {narrative_count} narrativos)",
    ]

    if countries:
        summary_parts.append(f"Países detectados: {', '.join(sorted(countries))}")
    if banderas:
        summary_parts.append(f"Banderas detectadas: {', '.join(sorted(banderas))}")
    if dates:
        summary_parts.append(f"Períodos: {', '.join(sorted(dates)[:10])}")

    summary_parts.append(f"\nContenido: Este archivo contiene datos de fee de bandera y/o facturas "
                         f"con información financiera detallada sobre transacciones y comisiones.")

    if sample_texts:
        summary_parts.append(f"\nMuestra del contenido:")
        for i, st in enumerate(sample_texts[:3], 1):
            summary_parts.append(f"  Chunk {i}: {st[:200]}...")

    return "\n".join(summary_parts)


def extract_narrative_chunks(chunks):
    """Extract non-tabular chunks that have meaningful text."""
    narrative = []
    for c in chunks:
        text = c.get("text", "").strip()
        if not text or len(text) < 30:
            continue
        if not is_tabular(text):
            narrative.append(c)
    return narrative


def rechunk_file(json_path, dry_run=False):
    """Rechunk a single cleaned JSON, replacing tabular chunks with summary."""
    with open(json_path) as f:
        data = json.load(f)

    file_name = data.get("file_name", json_path.stem)
    file_type = data.get("file_type", "")
    method = data.get("chunking_method", "")
    chunks = data.get("chunks", [])
    total = len(chunks)

    if total == 0:
        return None

    tabular_count = sum(1 for c in chunks if is_tabular(c.get("text", "")))
    tabular_pct = tabular_count / total * 100

    # Only process files that need it
    if file_type not in ("xlsx", "csv"):
        return None
    if method == "summary_analytical":
        return None  # Already summarized
    if tabular_pct < 50 and total < 100:
        return None  # Not enough tabular content

    if dry_run:
        return {
            "file": file_name[:60],
            "old_chunks": total,
            "tabular": tabular_count,
            "pct": round(tabular_pct, 1),
        }

    # Extract narrative chunks (keep as-is)
    narrative_chunks = extract_narrative_chunks(chunks)

    # Generate analytical summary for tabular data
    summary_text = extract_key_info_from_chunks(chunks, file_name)

    # Collect metadata from original chunks (most common values)
    meta_values = defaultdict(Counter)
    for c in chunks:
        meta = c.get("metadata", {})
        for field in ("team", "country", "bandera", "fecha"):
            val = meta.get(field, "")
            if isinstance(val, list):
                for v in val:
                    if v:
                        meta_values[field][v] += 1
            elif val:
                meta_values[field][val] += 1

    # Build consensus metadata
    consensus_meta = {}
    for field in ("team", "country", "bandera", "fecha"):
        counts = meta_values[field]
        if counts:
            # Use most common value(s)
            most_common = counts.most_common(3)
            if len(most_common) == 1:
                consensus_meta[field] = most_common[0][0]
            else:
                consensus_meta[field] = [mc[0] for mc in most_common]
        else:
            consensus_meta[field] = ""

    # Build new chunks list
    new_chunks = []

    # Add summary chunk first
    new_chunks.append({
        "chunk_index": 0,
        "text": summary_text,
        "metadata": {
            "team": consensus_meta.get("team", ""),
            "country": consensus_meta.get("country", ""),
            "bandera": consensus_meta.get("bandera", ""),
            "fecha": consensus_meta.get("fecha", ""),
            "section_title": "Resumen analítico",
            "page_number": None,
            "sheet_name": "",
            "slide_number": None,
        }
    })

    # Add narrative chunks (re-indexed)
    for i, nc in enumerate(narrative_chunks, 1):
        nc["chunk_index"] = i
        new_chunks.append(nc)

    # Update the cleaned JSON
    data["chunks"] = new_chunks
    data["total_chunks"] = len(new_chunks)
    data["chunking_method"] = "summary_analytical"
    data["rechunked_at"] = datetime.now(timezone.utc).isoformat()
    data["rechunk_info"] = {
        "original_chunks": total,
        "original_tabular": tabular_count,
        "new_chunks": len(new_chunks),
        "narrative_preserved": len(narrative_chunks),
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return {
        "file": file_name[:60],
        "old_chunks": total,
        "new_chunks": len(new_chunks),
        "narrative_kept": len(narrative_chunks),
        "reduction": f"{(1 - len(new_chunks)/total)*100:.1f}%",
    }


def main():
    parser = argparse.ArgumentParser(description="Rechunk tabular files with analytical summaries")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be rechunked")
    parser.add_argument("--min-chunks", type=int, default=10,
                        help="Minimum chunk count to consider for rechunking (default: 10)")
    args = parser.parse_args()

    if not CLEANED_DIR.exists():
        print("ERROR: No cleaned JSONs found.")
        sys.exit(1)

    json_files = sorted(CLEANED_DIR.glob("*.json"))
    print(f"Scanning {len(json_files)} cleaned JSONs...")

    results = []
    total_old = 0
    total_new = 0

    for jp in json_files:
        try:
            result = rechunk_file(jp, dry_run=args.dry_run)
            if result:
                results.append(result)
                if not args.dry_run:
                    total_old += result["old_chunks"]
                    total_new += result["new_chunks"]
        except Exception as e:
            print(f"  ERROR: {jp.name}: {e}")

    if not results:
        print("No files need rechunking.")
        return

    print(f"\n{'='*70}")
    if args.dry_run:
        print(f"DRY RUN — {len(results)} files would be rechunked:")
        print(f"{'File':<55} {'Old':>7} {'Tab':>7} {'Pct':>6}")
        print("-" * 80)
        total = 0
        for r in sorted(results, key=lambda x: -x["old_chunks"]):
            print(f"{r['file']:<55} {r['old_chunks']:>7} {r['tabular']:>7} {r['pct']:>5}%")
            total += r["old_chunks"]
        print(f"\nTotal chunks that would be replaced: {total:,}")
    else:
        print(f"RECHUNKED {len(results)} files:")
        print(f"{'File':<50} {'Old':>7} {'New':>5} {'Kept':>5} {'Reduction':>10}")
        print("-" * 80)
        for r in sorted(results, key=lambda x: -x["old_chunks"]):
            print(f"{r['file']:<50} {r['old_chunks']:>7} {r['new_chunks']:>5} {r['narrative_kept']:>5} {r['reduction']:>10}")
        print(f"\nTotal: {total_old:,} chunks → {total_new:,} chunks ({(1-total_new/total_old)*100:.1f}% reduction)")


if __name__ == "__main__":
    main()
