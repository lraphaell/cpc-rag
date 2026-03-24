#!/usr/bin/env python3
"""
Data Cleanup — Prepare Chunks

Parse downloaded files, chunk them, and produce intermediate JSON files
in .tmp/cleaned/ for agent-driven metadata extraction.

The output JSONs contain chunk text but metadata fields (team, country,
bandera, fecha) are left empty — they will be filled by the agent
analyzing each chunk's content.

Usage:
    PYTHONPATH=. python tools/cleanup/prepare_chunks.py
    PYTHONPATH=. python tools/cleanup/prepare_chunks.py --change-manifest .tmp/change_manifest.json

Output:
    .tmp/cleaned/{drive_id}.json per file
    .tmp/cleanup_manifest.json with summary
"""

import base64
import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

from tools.common.config import (
    TMP_DIR, DOWNLOADS_DIR,
    MAX_CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS,
)

CLEANED_DIR = TMP_DIR / "cleaned"

# Map file extensions to parser types
EXTENSION_TO_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".txt": "txt",
    ".md": "txt",
}


def get_parser_for_file(file_path):
    """Get the appropriate parser for a file based on extension."""
    ext = Path(file_path).suffix.lower()
    file_type = EXTENSION_TO_TYPE.get(ext)

    if not file_type:
        return None, None

    try:
        from tools.processing.parsers import get_parser
        return get_parser(file_type), file_type
    except ImportError:
        try:
            from tools.parsers import get_parser
            return get_parser(file_type), file_type
        except ImportError:
            return None, None


def get_chunker(method="semantic"):
    """Get a chunker by method name."""
    try:
        from tools.processing.chunkers import get_chunker as _get
        return _get(method)
    except ImportError:
        try:
            from tools.chunkers import get_chunker as _get
            return _get(method)
        except ImportError:
            return None


def basic_chunk(text, chunk_size=512, overlap=50):
    """Fallback chunker: simple word-based splitting."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk_words = words[i:i + chunk_size]
        chunks.append(" ".join(chunk_words))
        i += chunk_size - overlap
    return chunks


DIGIT_THRESHOLD = 0.12


def is_tabular_text(text):
    """Check if text is raw tabular/transactional data (high digit ratio)."""
    if not text or len(text) < 100:
        return False
    return sum(1 for ch in text if ch.isdigit()) / len(text) > DIGIT_THRESHOLD


def summarize_spreadsheet(parsed_result, file_name):
    """
    Generate analytical summary chunks from spreadsheet data instead of raw text.

    For spreadsheets with mostly numeric/transactional data, creates descriptive
    summaries useful for semantic search. Returns None if data is narrative.

    Args:
        parsed_result: Dict from spreadsheet_parser with 'text', 'metadata', 'raw_data'
        file_name: Original file name for context

    Returns:
        List of summary text strings, or None if data is narrative (use normal chunking)
    """
    raw_text = parsed_result.get("text", "")
    if not is_tabular_text(raw_text):
        return None

    metadata = parsed_result.get("metadata", {})
    raw_data = parsed_result.get("raw_data")
    summaries = []

    header = f"Archivo: {file_name}\n"
    if metadata.get("type") == "XLSX":
        header += f"Tipo: Planilla Excel con {metadata.get('sheet_count', '?')} hojas\n"
        header += f"Total filas: {metadata.get('total_rows', '?')}, Columnas: {metadata.get('total_columns', '?')}\n"
        if metadata.get("sheet_names"):
            header += f"Hojas: {', '.join(metadata['sheet_names'])}\n"
    elif metadata.get("type") == "CSV":
        header += f"Tipo: CSV con {metadata.get('row_count', '?')} filas y {metadata.get('column_count', '?')} columnas\n"
        if metadata.get("columns"):
            header += f"Columnas: {', '.join(str(c) for c in metadata['columns'][:20])}\n"

    if isinstance(raw_data, dict):
        for sheet_name, df in raw_data.items():
            summary = f"{header}Hoja: {sheet_name}\n"
            summary += f"Filas: {len(df)}, Columnas: {len(df.columns)}\n"
            summary += f"Nombres de columnas: {', '.join(str(c) for c in df.columns[:15])}\n"

            numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
            if numeric_cols:
                summary += f"\nColumnas numéricas: {', '.join(str(c) for c in numeric_cols[:10])}\n"
                for col in numeric_cols[:5]:
                    try:
                        summary += f"  {col}: min={df[col].min():.2f}, max={df[col].max():.2f}, promedio={df[col].mean():.2f}\n"
                    except (ValueError, TypeError):
                        pass

            cat_cols = df.select_dtypes(include=["object"]).columns.tolist()
            for col in cat_cols[:5]:
                uniques = df[col].dropna().unique()
                if 1 < len(uniques) <= 20:
                    vals = ", ".join(str(v) for v in uniques[:10])
                    extra = f" (+{len(uniques)-10} más)" if len(uniques) > 10 else ""
                    summary += f"  {col}: {vals}{extra}\n"

            sample = df.head(3).fillna("").to_string(index=False)
            if len(sample) < 500:
                summary += f"\nPrimeras filas (muestra):\n{sample}\n"

            summaries.append(summary)

    elif hasattr(raw_data, "columns"):
        df = raw_data
        summary = header
        summary += f"Nombres de columnas: {', '.join(str(c) for c in df.columns[:15])}\n"

        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if numeric_cols:
            summary += f"\nColumnas numéricas: {', '.join(str(c) for c in numeric_cols[:10])}\n"
            for col in numeric_cols[:5]:
                try:
                    summary += f"  {col}: min={df[col].min():.2f}, max={df[col].max():.2f}, promedio={df[col].mean():.2f}\n"
                except (ValueError, TypeError):
                    pass

        sample = df.head(3).fillna("").to_string(index=False)
        if len(sample) < 500:
            summary += f"\nPrimeras filas (muestra):\n{sample}\n"

        summaries.append(summary)

    if not summaries:
        summaries.append(header + "\n" + raw_text[:500])

    return summaries


def prepare_file(file_path, file_info):
    """
    Parse and chunk a single file, producing an intermediate JSON.

    Args:
        file_path: Path to the downloaded file
        file_info: Dict with drive_id, name, url, source, pic, etc.

    Returns:
        dict: {status, output_path, chunk_count} or {status: "error", error: str}
    """
    drive_id = file_info.get("drive_id", "unknown")
    file_name = file_info.get("name", Path(file_path).name)

    print(f"\n  Preparing: {file_name}")

    # 1. Parse
    parser, file_type = get_parser_for_file(file_path)
    if parser is None:
        return {"status": "skipped", "reason": f"no parser for {Path(file_path).suffix}"}

    try:
        parsed = parser.parse(str(file_path))
        if isinstance(parsed, dict):
            text = parsed.get("text", "")
            parse_metadata = parsed.get("metadata", {})
        else:
            text = str(parsed)
            parse_metadata = {}
    except Exception as e:
        return {"status": "error", "error": f"parse failed: {e}"}

    if not text or len(text.strip()) < 10:
        return {"status": "skipped", "reason": "empty or too short after parsing"}

    print(f"    Parsed: {len(text)} chars")

    # 2. Chunk — strategy depends on file type
    chunking_method = "semantic"
    chunk_texts = None

    # For spreadsheets, try to summarize tabular data instead of raw chunking
    if file_type in ("xlsx", "csv") and isinstance(parsed, dict):
        summaries = summarize_spreadsheet(parsed, file_name)
        if summaries:
            chunk_texts = summaries
            chunking_method = "summary_analytical"
            print(f"    Tabular data detected — generated {len(summaries)} analytical summaries")

    # For PPTX: use per-slide chunking (1 rich text chunk per slide)
    per_slide_data = parsed.get("per_slide_data") if isinstance(parsed, dict) else None
    if file_type == "pptx" and per_slide_data and chunk_texts is None:
        chunk_texts = []
        for sd in per_slide_data:
            slide_text = sd.get("raw_text", "").strip()
            if len(slide_text) > 20:  # Skip near-empty slides
                header = f"=== Slide {sd['slide_number']}"
                if sd.get("title"):
                    header += f": {sd['title']}"
                header += " ===\n"
                chunk_texts.append(header + slide_text)
        chunking_method = "per_slide"
        vision_count = parsed.get("metadata", {}).get("vision_enriched_slides", 0)
        if vision_count:
            chunking_method = f"per_slide+vision({vision_count})"
        print(f"    Per-slide chunking: {len(chunk_texts)} slides with content")

    # Normal semantic chunking for narrative text (DOCX, PDF, TXT, etc.)
    if chunk_texts is None:
        chunker = get_chunker("semantic")
        if chunker:
            try:
                chunk_texts = chunker.chunk(text, chunk_size=MAX_CHUNK_SIZE_TOKENS,
                                            overlap=CHUNK_OVERLAP_TOKENS)
            except Exception:
                chunk_texts = basic_chunk(text, MAX_CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS)
        else:
            chunk_texts = basic_chunk(text, MAX_CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS)

    if not chunk_texts:
        return {"status": "skipped", "reason": "no chunks generated"}

    print(f"    Chunks: {len(chunk_texts)} ({chunking_method})")

    # 3. Build intermediate JSON with empty metadata for agent extraction
    chunks_data = []
    for idx, chunk_text in enumerate(chunk_texts):
        chunk_entry = {
            "chunk_index": idx,
            "text": chunk_text,
            "content_type": "text",
            "metadata": {
                "team": "",
                "country": "",
                "bandera": "",
                "fecha": "",
                "section_title": "",
                "page_number": None,
                "sheet_name": "",
                "slide_number": None,
            }
        }
        # For per-slide chunks, set slide_number from the header
        if chunking_method.startswith("per_slide") and chunk_text.startswith("=== Slide "):
            try:
                parts = chunk_text.split("===", 2)
                slide_header = parts[1].strip()
                slide_n = int(slide_header.split(":")[0].replace("Slide", "").strip())
                chunk_entry["metadata"]["slide_number"] = slide_n
            except (IndexError, ValueError):
                pass
        chunks_data.append(chunk_entry)

    # 3b. Save slide images to disk for frontend display (NOT for embedding)
    slide_images = parsed.get("slide_images", []) if isinstance(parsed, dict) else []
    if slide_images:
        images_dir = TMP_DIR / "slide_images" / drive_id
        images_dir.mkdir(parents=True, exist_ok=True)
        saved = 0
        for img_data in slide_images:
            slide_num = img_data.get("slide_number", 0)
            img_bytes = img_data.get("image_bytes", b"")
            mime_type = img_data.get("mime_type", "image/png")
            if not img_bytes:
                continue
            ext = "png" if "png" in mime_type else "jpg"
            img_path = images_dir / f"slide_{slide_num:03d}.{ext}"
            img_path.write_bytes(img_bytes)
            saved += 1
        if saved:
            print(f"    Saved {saved} slide images to disk (display only, not embedded)")

    # Add parse-level metadata hints (if parser extracted page numbers, sections, etc.)
    if isinstance(parse_metadata, dict):
        for chunk in chunks_data:
            for key in ("section_title", "page_number", "sheet_name", "slide_number"):
                if key in parse_metadata and parse_metadata[key] is not None:
                    chunk["metadata"][key] = parse_metadata[key]

    # 4. Write intermediate JSON
    output = {
        "drive_id": drive_id,
        "file_name": file_name,
        "file_type": file_type or "",
        "source_url": file_info.get("url", ""),
        "source": file_info.get("source", ""),
        "pic": file_info.get("pic", ""),
        "modified_time": file_info.get("modified_time", ""),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "total_chunks": len(chunks_data),
        "chunking_method": chunking_method,
        "metadata_status": "pending_agent_review",
        "chunks": chunks_data,
    }

    CLEANED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CLEANED_DIR / f"{drive_id}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"    Saved: {output_path}")

    return {
        "status": "prepared",
        "output_path": str(output_path),
        "chunk_count": len(chunks_data),
    }


def find_downloaded_file(file_info):
    """Find the downloaded file in DOWNLOADS_DIR matching the file_info."""
    drive_id = file_info.get("drive_id", "")
    name = file_info.get("name", "")

    # Check download_manifest.json for exact path
    manifest_path = TMP_DIR / "download_manifest.json"
    if manifest_path.exists():
        with open(manifest_path, "r") as f:
            dl_manifest = json.load(f)
        for result in dl_manifest.get("results", []):
            if result.get("drive_id") == drive_id and result.get("success"):
                path = result.get("local_path")
                if path and os.path.exists(path):
                    return path

    # Fallback: search DOWNLOADS_DIR
    if DOWNLOADS_DIR.exists():
        for f in DOWNLOADS_DIR.iterdir():
            if f.is_file() and (f.stem in name or name in f.stem):
                return str(f)

    return None


def prepare_all(change_manifest_path=None):
    """
    Prepare all changed files from a change manifest.

    Args:
        change_manifest_path: Path to change_manifest.json

    Returns:
        dict: Cleanup manifest with results
    """
    if change_manifest_path is None:
        change_manifest_path = TMP_DIR / "change_manifest.json"

    with open(change_manifest_path, "r") as f:
        manifest = json.load(f)

    changes = manifest.get("changes", [])
    to_process = [c for c in changes if c["action"] in ("add", "update")]

    if not to_process:
        print("No files to prepare (no add/update changes).")
        return {"files": [], "summary": {"total": 0}}

    print(f"Preparing {len(to_process)} files for metadata extraction...")

    results = []
    for change in to_process:
        file_info = change["file_info"]
        local_path = find_downloaded_file(file_info)

        if not local_path:
            results.append({
                "drive_id": file_info.get("drive_id"),
                "file_name": file_info.get("name"),
                "status": "error",
                "error": "downloaded file not found in .tmp/downloads/",
            })
            continue

        result = prepare_file(local_path, file_info)
        result["drive_id"] = file_info.get("drive_id")
        result["file_name"] = file_info.get("name")
        results.append(result)

    cleanup_manifest = {
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "cleaned_dir": str(CLEANED_DIR),
        "files": results,
        "summary": {
            "total": len(to_process),
            "prepared": sum(1 for r in results if r["status"] == "prepared"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "errors": sum(1 for r in results if r["status"] == "error"),
            "total_chunks": sum(r.get("chunk_count", 0) for r in results),
        },
    }

    manifest_path = TMP_DIR / "cleanup_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(cleanup_manifest, f, indent=2, ensure_ascii=False)

    s = cleanup_manifest["summary"]
    print(f"\nPrepared: {s['prepared']}, Skipped: {s['skipped']}, Errors: {s['errors']}")
    print(f"Total chunks awaiting metadata: {s['total_chunks']}")
    print(f"Cleanup manifest: {manifest_path}")
    print(f"Cleaned JSONs in: {CLEANED_DIR}")

    return cleanup_manifest


def main():
    parser = argparse.ArgumentParser(description="Prepare chunks for metadata extraction")
    parser.add_argument("--change-manifest", default=str(TMP_DIR / "change_manifest.json"))
    args = parser.parse_args()

    prepare_all(args.change_manifest)


if __name__ == "__main__":
    main()
