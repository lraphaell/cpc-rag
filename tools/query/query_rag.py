#!/usr/bin/env python3
"""
Query RAG System

Test RAG retrieval by querying Pinecone with natural language questions.

Usage:
    python tools/query_rag.py \
        --question "What are the relevant topics for MLB in 2026?" \
        --namespace "genova-test" \
        --top_k 5
"""

import os
import sys
import argparse
from typing import List, Dict
from dotenv import load_dotenv

# Load environment
load_dotenv()


def query_pinecone(index, question: str, namespace: str, top_k: int = 5) -> List[Dict]:
    """
    Query Pinecone index with natural language question.

    Uses Gemini Embedding 2 to generate query vector, then searches Pinecone.

    Args:
        index: Pinecone index object
        question: Natural language question
        namespace: Pinecone namespace
        top_k: Number of results to return

    Returns:
        List of retrieved chunks with scores
    """
    from tools.embedding.gemini_embedder import GeminiEmbedder

    embedder = GeminiEmbedder()
    query_vector = embedder.embed_query(question)

    response = index.query(
        namespace=namespace,
        vector=query_vector,
        top_k=top_k,
        include_metadata=True
    )

    results = []
    for match in response.get('matches', []):
        results.append({
            'id': match['id'],
            'score': match.get('score', 0.0),
            'metadata': match.get('metadata', {})
        })

    return results


def display_chunk(chunk: Dict, index: int, total: int):
    """Display a single retrieved chunk."""
    print(f"\n{'=' * 80}")
    print(f"CHUNK {index + 1} of {total} (Relevance Score: {chunk['score']:.4f})")
    print(f"{'=' * 80}")

    metadata = chunk.get('metadata', {})

    print(f"\n📄 Source:")
    print(f"   Chunk ID: {chunk['id']}")
    print(f"   File: {metadata.get('file_name', 'N/A')}")
    print(f"   File Type: {metadata.get('file_type', 'N/A')}")

    if 'sheet_name' in metadata:
        print(f"   Sheet: {metadata.get('sheet_name')}")

    if 'slide_number' in metadata:
        print(f"   Slide: {metadata.get('slide_number')}")
        print(f"   Title: {metadata.get('slide_title', 'N/A')}")

    if 'chunk_index' in metadata:
        print(f"   Chunk Index: {metadata.get('chunk_index')}")

    text = metadata.get('text', '')
    print(f"\n📝 Content ({len(text)} chars):")
    print(f"   {'-' * 76}")

    # Show first 600 chars
    display_text = text[:600] if len(text) > 600 else text
    # Indent each line
    for line in display_text.split('\n'):
        print(f"   {line}")

    if len(text) > 600:
        print(f"\n   ... +{len(text) - 600} more characters")

    print(f"   {'-' * 76}")


def synthesize_answer(question: str, chunks: List[Dict]) -> str:
    """
    Synthesize answer from retrieved chunks.

    In production, this would use an LLM. For now, we'll extract relevant info.
    """
    if not chunks:
        return "No relevant information found in the knowledge base."

    # For this demo, we'll concatenate relevant parts
    answer_parts = []

    # Check if any chunks are highly relevant (score > 0.7)
    relevant_chunks = [c for c in chunks if c['score'] > 0.5]

    if not relevant_chunks:
        return f"Found {len(chunks)} potentially relevant chunks, but none with high relevance scores. Top result score: {chunks[0]['score']:.4f}"

    # Extract key information
    for chunk in relevant_chunks[:3]:  # Top 3 most relevant
        text = chunk['metadata'].get('text', '')
        # Get first 300 chars as summary
        summary = text[:300].replace('\n', ' ').strip()
        answer_parts.append(summary)

    return "\n\n".join(answer_parts)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Query RAG system with natural language questions"
    )
    parser.add_argument(
        "--question",
        required=True,
        help="Natural language question to query"
    )
    parser.add_argument(
        "--namespace",
        default="genova-test",
        help="Pinecone namespace (default: 'genova-test')"
    )
    parser.add_argument(
        "--top_k",
        type=int,
        default=5,
        help="Number of results to retrieve (default: 5)"
    )

    args = parser.parse_args()

    print("=" * 80)
    print("RAG QUERY TEST")
    print("=" * 80)

    # Validate environment
    api_key = os.getenv('PINECONE_API_KEY')
    index_name = os.getenv('PINECONE_INDEX_NAME')

    if not api_key:
        print("✗ Error: PINECONE_API_KEY not set in .env", file=sys.stderr)
        return 1

    if not index_name:
        print("✗ Error: PINECONE_INDEX_NAME not set in .env", file=sys.stderr)
        return 1

    print(f"\n📊 Query Configuration:")
    print(f"   Index: {index_name}")
    print(f"   Namespace: {args.namespace}")
    print(f"   Top K: {args.top_k}")
    print(f"\n❓ Question: \"{args.question}\"")
    print()

    # Connect to Pinecone
    print("Connecting to Pinecone...")
    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=api_key)
        index = pc.Index(index_name)

        # Get stats
        stats = index.describe_index_stats()
        vector_count = stats.get('namespaces', {}).get(args.namespace, {}).get('vector_count', 0)

        print(f"✓ Connected to index: {index_name}")
        print(f"✓ Namespace '{args.namespace}' has {vector_count} vectors")
        print()

    except ImportError:
        print("✗ Error: pinecone-client not installed", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"✗ Error connecting to Pinecone: {e}", file=sys.stderr)
        return 1

    # Query
    print(f"🔍 Searching for relevant chunks...")
    try:
        results = query_pinecone(index, args.question, args.namespace, args.top_k)

        if not results:
            print("⚠️  No results found")
            return 1

        print(f"✓ Retrieved {len(results)} chunks\n")

        # Display retrieved chunks
        print("=" * 80)
        print("RETRIEVED CHUNKS")
        print("=" * 80)

        for idx, chunk in enumerate(results):
            display_chunk(chunk, idx, len(results))

        # Synthesize answer
        print("\n" + "=" * 80)
        print("SYNTHESIZED ANSWER")
        print("=" * 80)
        print()

        answer = synthesize_answer(args.question, results)
        print(answer)

        # Summary
        print("\n" + "=" * 80)
        print("RETRIEVAL STRUCTURE")
        print("=" * 80)
        print(f"\n✓ Question: {args.question}")
        print(f"✓ Retrieved: {len(results)} chunks")
        print(f"✓ Top score: {results[0]['score']:.4f}")
        print(f"✓ Sources:")

        # Group by file
        files = {}
        for chunk in results:
            file_name = chunk['metadata'].get('file_name', 'Unknown')
            if file_name not in files:
                files[file_name] = []
            files[file_name].append(chunk['id'])

        for file_name, chunk_ids in files.items():
            print(f"   • {file_name}: {len(chunk_ids)} chunk(s)")

        print("\n✓ Embedding Model: gemini-embedding-2-preview (Gemini)")
        print("✓ Retrieval Method: Semantic similarity search")
        print("=" * 80)

        return 0

    except Exception as e:
        print(f"\n✗ Error during query: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
