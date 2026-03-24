#!/usr/bin/env python3
"""
Create a new Pinecone serverless index for Gemini Embedding 2 vectors.

This creates a 768-dimensional index (cosine metric) without integrated
inference, since embeddings are pre-computed by Gemini.

Usage:
    PYTHONPATH=. python tools/ingestion/create_gemini_index.py

    # Custom name:
    PYTHONPATH=. python tools/ingestion/create_gemini_index.py --name my-index
"""

import argparse
import sys
import time

from tools.common.config import PINECONE_API_KEY, EMBEDDING_DIMENSIONS


def main():
    parser = argparse.ArgumentParser(description="Create Pinecone index for Gemini embeddings")
    parser.add_argument("--name", default="genova-gemini-768", help="Index name")
    parser.add_argument("--cloud", default="aws", help="Cloud provider")
    parser.add_argument("--region", default="us-east-1", help="Cloud region")
    args = parser.parse_args()

    if not PINECONE_API_KEY:
        print("Error: PINECONE_API_KEY not set", file=sys.stderr)
        return 1

    from pinecone import Pinecone, ServerlessSpec

    pc = Pinecone(api_key=PINECONE_API_KEY)

    # Check if index already exists
    existing = [idx.name for idx in pc.list_indexes()]
    if args.name in existing:
        print(f"Index '{args.name}' already exists.")
        desc = pc.describe_index(args.name)
        print(f"  Dimension: {desc.dimension}")
        print(f"  Metric: {desc.metric}")
        return 0

    print(f"Creating index '{args.name}'...")
    print(f"  Dimension: {EMBEDDING_DIMENSIONS}")
    print(f"  Metric: cosine")
    print(f"  Spec: serverless ({args.cloud}/{args.region})")

    pc.create_index(
        name=args.name,
        dimension=EMBEDDING_DIMENSIONS,
        metric="cosine",
        spec=ServerlessSpec(cloud=args.cloud, region=args.region),
    )

    # Wait for index to be ready
    print("Waiting for index to be ready...")
    while not pc.describe_index(args.name).status.get("ready", False):
        time.sleep(2)
        print("  ...")

    print(f"Index '{args.name}' is ready!")
    print(f"\nNext steps:")
    print(f"  1. Update .env: PINECONE_INDEX_NAME={args.name}")
    print(f"  2. Run: PINECONE_INDEX_NAME={args.name} PYTHONPATH=. python tools/ingestion/process_and_ingest.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
