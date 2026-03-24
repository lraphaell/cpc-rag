#!/usr/bin/env python3
"""
Ingest cleaned chunks into Pinecone from intermediate JSONs.

Reads from .tmp/cleaned/{drive_id}.json (produced by prepare_chunks.py
and enriched with metadata by the agent).

For updated files: deletes old chunks first, then re-ingests.
For deleted files: deletes all chunks from Pinecone.

Usage:
    # Ingest all reviewed files:
    PYTHONPATH=. python tools/ingestion/process_and_ingest.py

    # Ingest from change manifest (handles add/update/delete):
    PYTHONPATH=. python tools/ingestion/process_and_ingest.py --change-manifest .tmp/change_manifest.json

    # Ingest specific files by drive_id:
    PYTHONPATH=. python tools/ingestion/process_and_ingest.py --files id1,id2

Output:
    .tmp/ingestion_log.json with processing results
"""

import json
import os
import sys
import glob
import argparse
from datetime import datetime, timezone
from pathlib import Path

from tools.common.config import TMP_DIR, PINECONE_NAMESPACE, DOWNLOADS_DIR
from tools.ingestion.pinecone_client import PineconeClient, flatten_metadata
from tools.embedding.gemini_embedder import GeminiEmbedder
from tools.state.update_state import update_file_state, remove_file_state, compute_file_hash

CLEANED_DIR = TMP_DIR / "cleaned"


def ingest_cleaned_file(cleaned_json_path, client, namespace, embedder=None):
    """
    Ingest a single cleaned JSON file into Pinecone.

    Generates embeddings via Gemini Embedding 2 and upserts
    pre-embedded vectors to Pinecone.

    Args:
        cleaned_json_path: Path to the cleaned JSON
        client: PineconeClient instance
        namespace: Pinecone namespace
        embedder: GeminiEmbedder instance (shared across files)

    Returns:
        dict: {status, chunk_count, chunk_ids, ...}
    """
    if embedder is None:
        embedder = GeminiEmbedder()

    with open(cleaned_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    drive_id = data.get("drive_id", "")
    file_name = data.get("file_name", "")
    metadata_status = data.get("metadata_status", "")

    if metadata_status != "reviewed":
        return {
            "status": "skipped",
            "reason": f"metadata_status is '{metadata_status}', expected 'reviewed'",
        }

    chunks = data.get("chunks", [])
    if not chunks:
        return {"status": "skipped", "reason": "no chunks"}

    print(f"  Ingesting: {file_name} ({len(chunks)} chunks)")

    # Build records with metadata (text-only — image chunks no longer embedded)
    records = []
    chunk_ids = []

    for chunk in chunks:
        idx = chunk.get("chunk_index", 0)
        chunk_id = f"{drive_id}_{idx:04d}"
        content_type = chunk.get("content_type", "text")

        # Skip image chunks (kept on disk for display, not embedded)
        if content_type == "slide_image":
            continue

        # Skip raw tabular chunks (>12% digits = transactional data, not useful for QA)
        text = chunk.get("text", "")
        if text and len(text) > 100:
            digit_ratio = sum(1 for ch in text if ch.isdigit()) / len(text)
            if digit_ratio > 0.12:
                continue

        chunk_ids.append(chunk_id)

        # Start with chunk-level metadata (filled by agent)
        chunk_meta = chunk.get("metadata", {})

        # Add file-level technical fields
        metadata = {
            "drive_file_id": drive_id,
            "file_name": file_name,
            "file_type": data.get("file_type", ""),
            "chunk_index": idx,
            "total_chunks": data.get("total_chunks", len(chunks)),
            "source_url": data.get("source_url", ""),
            "modified_time": data.get("modified_time", ""),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "chunking_method": data.get("chunking_method", ""),
            "content_type": "text",
        }

        # Merge chunk-level metadata (agent-extracted: team, country, bandera, fecha, etc.)
        for key, value in chunk_meta.items():
            if value is not None and value != "":
                metadata[key] = value

        flat = flatten_metadata(metadata)
        flat["text"] = text
        records.append({"id": chunk_id, "text": text, "metadata": flat})

    if not records:
        return {"status": "skipped", "reason": "all chunks filtered (tabular)"}

    pinecone_vectors = []

    # Generate text embeddings
    try:
        texts = [r["text"] for r in records]
        print(f"    Generating embeddings for {len(texts)} chunks...")
        vectors = embedder.embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")
        for record, vector in zip(records, vectors):
            pinecone_vectors.append({
                "id": record["id"],
                "values": vector,
                "metadata": record["metadata"],
            })
    except Exception as e:
        return {"status": "error", "error": f"embedding failed: {e}"}

    # Upsert to Pinecone
    try:
        upserted = client.upsert_vectors(pinecone_vectors, namespace=namespace)
        print(f"    Upserted: {upserted} vectors")

        # Update state
        update_file_state(drive_id, {
            "name": file_name,
            "modified_time": data.get("modified_time", ""),
            "content_hash": "",
            "pinecone_chunk_ids": chunk_ids,
            "chunk_count": len(chunk_ids),
        })

        return {
            "status": "success",
            "chunk_count": len(chunk_ids),
            "chunk_ids": chunk_ids,
        }

    except Exception as e:
        return {"status": "error", "error": f"upsert failed: {e}"}


def process_changes(change_manifest_path=None, namespace=None, file_ids=None):
    """
    Process all changes: ingest reviewed files, delete removed files.

    Args:
        change_manifest_path: Path to change_manifest.json (optional)
        namespace: Pinecone namespace
        file_ids: Specific drive_ids to ingest (optional, overrides manifest)

    Returns:
        dict: Ingestion log
    """
    ns = namespace or PINECONE_NAMESPACE
    client = PineconeClient()
    embedder = GeminiEmbedder()
    print(f"Connected to Pinecone index: {client.index_name}, namespace: {ns}")
    print(f"Embedding model: {embedder.model} ({embedder.dimensions} dims)")

    processed = []
    deleted = []

    if file_ids:
        # Ingest specific files
        for fid in file_ids:
            cleaned_path = CLEANED_DIR / f"{fid}.json"
            if not cleaned_path.exists():
                processed.append({"drive_id": fid, "status": "error", "error": "cleaned JSON not found"})
                continue

            result = ingest_cleaned_file(cleaned_path, client, ns, embedder)
            result["drive_id"] = fid
            processed.append(result)

    elif change_manifest_path and Path(change_manifest_path).exists():
        # Process from change manifest
        with open(change_manifest_path, "r") as f:
            manifest = json.load(f)

        for change in manifest.get("changes", []):
            action = change["action"]
            file_info = change["file_info"]
            drive_id = file_info.get("drive_id", "")
            name = file_info.get("name", "?")

            if action == "delete":
                print(f"\n  Deleting chunks for: {name}")
                success = client.delete_by_file(drive_id, namespace=ns)
                if success:
                    remove_file_state(drive_id)
                deleted.append({
                    "drive_id": drive_id,
                    "name": name,
                    "status": "deleted" if success else "delete_failed",
                })

            elif action in ("add", "update"):
                if action == "update":
                    print(f"\n  Updating: {name} (deleting old chunks first)")
                    client.delete_by_file(drive_id, namespace=ns)

                cleaned_path = CLEANED_DIR / f"{drive_id}.json"
                if not cleaned_path.exists():
                    processed.append({
                        "drive_id": drive_id,
                        "file_name": name,
                        "status": "error",
                        "error": "cleaned JSON not found — run prepare_chunks.py and metadata extraction first",
                    })
                    continue

                result = ingest_cleaned_file(cleaned_path, client, ns, embedder)
                result["drive_id"] = drive_id
                result["file_name"] = name
                processed.append(result)

    else:
        # Ingest all reviewed files in cleaned dir
        print("No change manifest — ingesting all reviewed files in .tmp/cleaned/")
        for json_path in sorted(CLEANED_DIR.glob("*.json")):
            with open(json_path) as f:
                data = json.load(f)
            if data.get("metadata_status") != "reviewed":
                continue

            drive_id = data.get("drive_id", json_path.stem)
            result = ingest_cleaned_file(json_path, client, ns, embedder)
            result["drive_id"] = drive_id
            result["file_name"] = data.get("file_name", "")
            processed.append(result)

    # Build summary
    log = {
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "namespace": ns,
        "processed_files": processed,
        "deleted_files": deleted,
        "summary": {
            "total": len(processed) + len(deleted),
            "success": sum(1 for p in processed if p.get("status") == "success"),
            "deleted": sum(1 for d in deleted if d["status"] == "deleted"),
            "errors": sum(1 for p in processed if p.get("status") == "error"),
            "skipped": sum(1 for p in processed if p.get("status") == "skipped"),
            "total_chunks": sum(p.get("chunk_count", 0) for p in processed),
        },
    }

    return log


def main():
    parser = argparse.ArgumentParser(description="Ingest cleaned chunks to Pinecone")
    parser.add_argument("--change-manifest", default=str(TMP_DIR / "change_manifest.json"))
    parser.add_argument("--namespace", default=None)
    parser.add_argument("--files", default=None, help="Comma-separated drive_ids to ingest")
    args = parser.parse_args()

    file_ids = args.files.split(",") if args.files else None
    log = process_changes(args.change_manifest, args.namespace, file_ids)

    # Save log
    log_path = TMP_DIR / "ingestion_log.json"
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    s = log["summary"]
    print(f"\n{'='*60}")
    print(f"INGESTION COMPLETE")
    print(f"{'='*60}")
    print(f"Success: {s.get('success', 0)}")
    print(f"Deleted: {s.get('deleted', 0)}")
    print(f"Errors:  {s.get('errors', 0)}")
    print(f"Skipped: {s.get('skipped', 0)}")
    print(f"Total chunks: {s.get('total_chunks', 0)}")
    print(f"\nLog saved to: {log_path}")


if __name__ == "__main__":
    main()
