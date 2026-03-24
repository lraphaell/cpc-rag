#!/usr/bin/env python3
"""
Generate one summary chunk per file using Gemini Flash.

For each cleaned JSON that doesn't already have a summary chunk, this script:
1. Collects up to ~3,000 chars of representative text from existing chunks
2. Calls Gemini Flash to produce a concise 150-200 word document summary
3. Creates a new chunk (chunk_index 0, content_type "summary") with consensus
   metadata inherited from the file's chunks
4. Prepends the summary chunk and re-numbers all other chunk_index values
5. Updates total_chunks in the JSON

Summary chunks improve retrieval for generic "what is X?" queries by surfacing
a document-level description before fragmented detail chunks.

Usage:
    PYTHONPATH=. python tools/cleanup/generate_summary_chunks.py
    PYTHONPATH=. python tools/cleanup/generate_summary_chunks.py --dry-run
    PYTHONPATH=. python tools/cleanup/generate_summary_chunks.py --file "filename"
    PYTHONPATH=. python tools/cleanup/generate_summary_chunks.py --limit 10
"""

import json
import sys
import time
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from tools.common.config import TMP_DIR, GEMINI_API_KEY

CLEANED_DIR = TMP_DIR / "cleaned"
SUMMARY_MARKER = "summary"
MAX_INPUT_CHARS = 3000   # chars sent to Gemini Flash for summarization
GEMINI_FLASH_MODEL = "gemini-2.5-flash"


# ── Gemini Flash client ───────────────────────────────────────────────────────

def _get_flash_client():
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set. Add it to .env")
    from google import genai
    return genai.Client(api_key=GEMINI_API_KEY)


def generate_summary(client, file_name: str, text_sample: str) -> str:
    """
    Call Gemini Flash to produce a 150-200 word summary of the document.
    Returns the summary text.
    """
    prompt = (
        f"Eres un asistente experto en documentos internos de Mercado Pago sobre el equipo Genova "
        f"(adquirencia de pagos con tarjeta).\n\n"
        f"Documento: {file_name}\n\n"
        f"Fragmento representativo:\n{text_sample}\n\n"
        f"Escribe un párrafo de 150-200 palabras en español que resuma este documento. "
        f"El resumen debe responder: ¿qué es este documento?, ¿de qué equipo/proyecto trata?, "
        f"¿qué países o banderas involucra?, ¿qué período cubre?, ¿cuál es el objetivo o contenido principal?. "
        f"Sé específico y usa el vocabulario del dominio (adquirencia, tasas, banderas, etc.). "
        f"No uses frases genéricas como 'este documento presenta' — ve directo al contenido."
    )

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "rate" in err.lower():
                wait = min(2 ** attempt + 2, 60)
                print(f"    Rate limited, waiting {wait}s (attempt {attempt + 1}/5)")
                time.sleep(wait)
            else:
                raise

    raise Exception(f"Gemini Flash failed after 5 retries for: {file_name}")


# ── Metadata consensus ────────────────────────────────────────────────────────

def _is_empty_or_default(val, field):
    defaults = {
        "team": ("", "Genova"),
        "country": ("", "Corp"),
        "bandera": ("", "Otra"),
        "fecha": ("",),
    }
    if isinstance(val, list):
        val = val[0] if val else ""
    return val in defaults.get(field, ("",))


def build_consensus_metadata(chunks: list) -> dict:
    """
    Build consensus metadata from all chunks (including defaults — we want
    the dominant value, even if it's Genova).
    Returns flat metadata dict for the summary chunk.
    """
    counters = {f: Counter() for f in ("team", "country", "bandera", "fecha")}

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        for field in counters:
            val = meta.get(field, "")
            if isinstance(val, list):
                for v in val:
                    if v:
                        counters[field][v] += 1
            elif val:
                counters[field][val] += 1

    result = {}
    for field, counter in counters.items():
        if not counter:
            result[field] = "" if field == "fecha" else ("Genova" if field == "team" else ("Corp" if field == "country" else "Otra"))
            continue
        top = counter.most_common(3)
        if len(top) == 1:
            result[field] = top[0][0]
        else:
            # Keep top values as list when multiple dominate equally
            result[field] = [v for v, _ in top if v]

    return result


# ── File-level processing ─────────────────────────────────────────────────────

def has_summary_chunk(chunks: list) -> bool:
    """Check if file already has a summary chunk."""
    for chunk in chunks:
        if chunk.get("content_type") == SUMMARY_MARKER:
            return True
        # Also check if chunk_index -1 or section_title indicates summary
        meta = chunk.get("metadata", {})
        if meta.get("section_title", "").lower() in ("resumen", "resumen analítico", "summary"):
            return True
    return False


def collect_text_sample(chunks: list, max_chars: int = MAX_INPUT_CHARS) -> str:
    """
    Collect a representative text sample from the file's chunks.
    Prioritizes text chunks and spreads across early, middle, and late chunks.
    """
    text_chunks = [c for c in chunks if c.get("content_type", "text") != "slide_image"]

    if not text_chunks:
        # Fall back to all chunks if only images
        text_chunks = chunks

    total = len(text_chunks)
    if total == 0:
        return ""

    # Pick representative indices: first 40%, middle 30%, last 30%
    early_end = max(1, int(total * 0.4))
    mid_start = int(total * 0.4)
    mid_end = int(total * 0.7)
    late_start = int(total * 0.7)

    selected = []
    selected.extend(text_chunks[:early_end])
    if mid_end > mid_start:
        selected.extend(text_chunks[mid_start:mid_end])
    selected.extend(text_chunks[late_start:])

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for c in selected:
        idx = c.get("chunk_index", -1)
        if idx not in seen:
            seen.add(idx)
            deduped.append(c)

    # Collect text up to max_chars
    parts = []
    total_chars = 0
    for chunk in deduped:
        text = chunk.get("text", "").strip()
        if not text:
            continue
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        parts.append(text[:remaining])
        total_chars += len(text[:remaining])

    return "\n\n".join(parts)


def process_file(filepath: Path, client, dry_run: bool = False) -> dict:
    """Process a single cleaned JSON, adding a summary chunk if missing."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    file_name = data.get("file_name", "")
    chunks = data.get("chunks", [])

    if not chunks:
        return {"file": file_name[:60], "status": "skipped", "reason": "no chunks"}

    if has_summary_chunk(chunks):
        return {"file": file_name[:60], "status": "skipped", "reason": "already has summary"}

    # Collect representative text
    text_sample = collect_text_sample(chunks)
    if not text_sample:
        return {"file": file_name[:60], "status": "skipped", "reason": "no text content"}

    if dry_run:
        return {
            "file": file_name[:60],
            "status": "would_add",
            "current_chunks": len(chunks),
            "sample_chars": len(text_sample),
        }

    # Generate summary via Gemini Flash
    summary_text = generate_summary(client, file_name, text_sample)

    # Build consensus metadata for summary chunk
    consensus_meta = build_consensus_metadata(chunks)

    # Create summary chunk
    summary_chunk = {
        "chunk_index": 0,
        "text": summary_text,
        "content_type": SUMMARY_MARKER,
        "metadata": {
            "team": consensus_meta.get("team", "Genova"),
            "country": consensus_meta.get("country", "Corp"),
            "bandera": consensus_meta.get("bandera", "Otra"),
            "fecha": consensus_meta.get("fecha", ""),
            "section_title": "Resumen del documento",
            "page_number": None,
            "sheet_name": "",
            "slide_number": None,
        },
    }

    # Renumber existing chunks (+1) and prepend summary
    for chunk in chunks:
        chunk["chunk_index"] = chunk.get("chunk_index", 0) + 1

    new_chunks = [summary_chunk] + chunks
    data["chunks"] = new_chunks
    data["total_chunks"] = len(new_chunks)
    data["summary_added_at"] = datetime.now(timezone.utc).isoformat()

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return {
        "file": file_name[:60],
        "status": "added",
        "total_chunks": len(new_chunks),
        "summary_words": len(summary_text.split()),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Add summary chunks to cleaned JSONs via Gemini Flash")
    parser.add_argument("--dry-run", action="store_true", help="Preview without calling Gemini or saving")
    parser.add_argument("--file", help="Process a single file (by name pattern)")
    parser.add_argument("--limit", type=int, help="Process at most N files")
    args = parser.parse_args()

    if args.file:
        matches = list(CLEANED_DIR.glob(f"*{args.file}*"))
        if not matches:
            print(f"No files matching: {args.file}")
            sys.exit(1)
        json_files = matches
    else:
        json_files = sorted(CLEANED_DIR.glob("*.json"))

    if args.limit:
        json_files = json_files[:args.limit]

    client = None if args.dry_run else _get_flash_client()

    mode = "DRY RUN" if args.dry_run else "PROCESSING"
    print(f"{mode}: {len(json_files)} files to check for summary chunks...\n")

    added = skipped = errors = 0
    start = time.time()

    for i, filepath in enumerate(json_files, 1):
        try:
            result = process_file(filepath, client, args.dry_run)
            status = result["status"]

            if status == "added":
                added += 1
                print(f"  [{i:3d}] ✓ {result['file']}")
                print(f"        {result['total_chunks']} chunks total | {result['summary_words']} words")
                # Small delay to respect Gemini rate limits
                time.sleep(0.5)
            elif status == "would_add":
                added += 1
                print(f"  [{i:3d}] → {result['file']} ({result['current_chunks']} chunks, {result['sample_chars']} chars sample)")
            else:
                skipped += 1
                if result.get("reason") != "already has summary":
                    print(f"  [{i:3d}] skip: {result['file']} — {result.get('reason')}")

        except Exception as e:
            errors += 1
            print(f"  [{i:3d}] ERROR: {filepath.name}: {e}", file=sys.stderr)

    elapsed = time.time() - start
    print(f"\n{'─'*60}")
    print(f"{mode} complete in {elapsed:.1f}s")
    print(f"  Added: {added} | Skipped: {skipped} | Errors: {errors}")
    if not args.dry_run and added > 0:
        print(f"\nNext step: re-ingest all files to genova-v2 to include new summary vectors.")


if __name__ == "__main__":
    main()
