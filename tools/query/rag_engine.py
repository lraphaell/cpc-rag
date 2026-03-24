#!/usr/bin/env python3
"""
RAG Engine - Retrieval-Augmented Generation Backend

Handles Pinecone vector retrieval and LLM answer synthesis.
Supports Google Gemini (primary) and Anthropic Claude (fallback).
Designed to be used by the Streamlit chat app or any other interface.

Usage:
    from rag_engine import RAGEngine

    engine = RAGEngine(
        pinecone_api_key="...",
        pinecone_index_name="agentic-rag",
        gemini_api_key="...",
        namespace="genova-prod"
    )

    result = engine.query("What are the MLB topics for 2026?")
    print(result["answer"])
    print(result["chunks"])
"""

import os
import sys
from typing import List, Dict, Optional

# Maximum characters of chunk text to include in the prompt context
MAX_CONTEXT_CHARS = 15000


class RAGEngine:
    """RAG engine combining Pinecone retrieval with LLM answer synthesis."""

    def __init__(
        self,
        pinecone_api_key: str,
        pinecone_index_name: str,
        gemini_api_key: str = "",
        anthropic_api_key: str = "",
        namespace: str = "genova-prod",
        gemini_model: str = "gemini-2.5-flash",
        claude_model: str = "claude-sonnet-4-20250514",
    ):
        """
        Initialize RAG engine.

        Args:
            pinecone_api_key: Pinecone API key
            pinecone_index_name: Name of the Pinecone index
            gemini_api_key: Google Gemini API key (preferred)
            anthropic_api_key: Anthropic API key for Claude (fallback)
            namespace: Pinecone namespace to query
            gemini_model: Gemini model to use for synthesis
            claude_model: Claude model to use for synthesis (fallback)
        """
        from pinecone import Pinecone

        self.pc = Pinecone(api_key=pinecone_api_key)
        self.index = self.pc.Index(pinecone_index_name)
        self.namespace = namespace
        self.gemini_model = gemini_model
        self.claude_model = claude_model

        # Embedder for query vectors (Gemini Embedding 2)
        from tools.embedding.gemini_embedder import GeminiEmbedder
        self.embedder = GeminiEmbedder(api_key=gemini_api_key)

        # LLM clients - try Gemini first, then Claude
        self.client = None
        self.llm_provider = None

        if gemini_api_key and gemini_api_key not in ("", "your_gemini_key_here"):
            from google import genai
            self.client = genai.Client(api_key=gemini_api_key)
            self.llm_provider = "gemini"
        elif anthropic_api_key and anthropic_api_key not in ("", "your_anthropic_key_here"):
            import anthropic
            self.client = anthropic.Anthropic(api_key=anthropic_api_key)
            self.llm_provider = "claude"

    def retrieve(self, question: str, top_k: int = 5) -> List[Dict]:
        """
        Retrieve relevant chunks from Pinecone using semantic search.

        Args:
            question: Natural language question
            top_k: Number of chunks to retrieve

        Returns:
            List of chunk dicts with id, score, text, file_name, file_type, etc.
        """
        # Generate query embedding via Gemini Embedding 2
        query_vector = self.embedder.embed_query(question)

        # Query Pinecone index
        results = self.index.query(
            namespace=self.namespace,
            vector=query_vector,
            top_k=top_k,
            include_metadata=True,
        )

        # Parse results into clean dicts
        chunks = []
        for match in results.matches:
            metadata = match.metadata
            chunks.append(
                {
                    "id": match.id,
                    "score": float(match.score),
                    "text": metadata.get("text", ""),
                    "file_name": metadata.get("file_name", "Unknown"),
                    "file_type": metadata.get("file_type", "Unknown"),
                    "file_id": metadata.get("file_id", ""),
                    "sheet_name": metadata.get("sheet_name", ""),
                    "slide_number": metadata.get("slide_number", ""),
                    "chunk_index": metadata.get("chunk_index", ""),
                }
            )

        return chunks

    def synthesize(self, question: str, chunks: List[Dict]) -> str:
        """
        Use LLM (Gemini or Claude) to synthesize an answer from retrieved chunks.

        Args:
            question: The user's question
            chunks: Retrieved chunks from Pinecone

        Returns:
            Synthesized answer string
        """
        if not chunks:
            return "No relevant information found in the knowledge base."

        if not self.client:
            return "No LLM API configured. Add GEMINI_API_KEY or ANTHROPIC_API_KEY to enable answer synthesis."

        # Build context from retrieved chunks (trim to avoid token limits)
        context_parts = []
        total_chars = 0

        for i, chunk in enumerate(chunks):
            text = chunk["text"]
            if len(text) > 4000:
                text = text[:4000] + "..."

            if total_chars + len(text) > MAX_CONTEXT_CHARS:
                break

            source = chunk["file_name"]
            if chunk.get("sheet_name"):
                source += f" (Sheet: {chunk['sheet_name']})"
            elif chunk.get("slide_number"):
                source += f" (Slide {chunk['slide_number']})"

            context_parts.append(
                f"[Source {i + 1}: {source} | Relevance: {chunk['score']:.3f}]\n{text}"
            )
            total_chars += len(text)

        context = "\n\n---\n\n".join(context_parts)

        system_prompt = (
            "You are a knowledgeable assistant for the Genova payment processing team at Core Payments Corp. "
            "Your role is to answer questions based ONLY on the provided context from the knowledge base. "
            "Follow these rules:\n"
            "1. Answer based strictly on the context provided. Do not make up information.\n"
            "2. If the context doesn't contain enough information, say so clearly.\n"
            "3. Always cite which document(s) your answer comes from using the source names.\n"
            "4. Answer in the same language as the question (Spanish or English).\n"
            "5. Be concise but thorough. Use bullet points for lists.\n"
            "6. If the data is from spreadsheets/tables, organize your answer clearly."
        )

        user_prompt = (
            f"Context from the Genova knowledge base:\n\n"
            f"{context}\n\n"
            f"---\n\n"
            f"Question: {question}"
        )

        try:
            if self.llm_provider == "gemini":
                full_prompt = f"{system_prompt}\n\n{user_prompt}"
                response = self.client.models.generate_content(
                    model=self.gemini_model,
                    contents=full_prompt,
                )
                return response.text
            else:
                # Claude
                response = self.client.messages.create(
                    model=self.claude_model,
                    max_tokens=1500,
                    timeout=30.0,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return response.content[0].text
        except Exception as e:
            return f"Error al generar respuesta del LLM ({self.llm_provider}): {e}"

    def query(self, question: str, top_k: int = 5) -> Dict:
        """
        Full RAG flow: retrieve relevant chunks then synthesize answer.

        Args:
            question: Natural language question
            top_k: Number of chunks to retrieve

        Returns:
            Dict with "answer", "chunks", "model", and "synthesis_mode"
        """
        chunks = self.retrieve(question, top_k=top_k)

        if self.client:
            answer = self.synthesize(question, chunks)
            mode = self.llm_provider
        else:
            # Retrieval-only mode: format chunks as the answer
            if chunks:
                parts = []
                for i, chunk in enumerate(chunks[:3]):
                    text = chunk["text"][:500]
                    parts.append(f"**Source: {chunk['file_name']}** (score: {chunk['score']:.3f})\n\n{text}...")
                answer = "**[Retrieval Only - No LLM API key configured]**\n\nTop matching content:\n\n" + "\n\n---\n\n".join(parts)
            else:
                answer = "No relevant information found."
            mode = "retrieval_only"

        model_name = self.gemini_model if self.llm_provider == "gemini" else (
            self.claude_model if self.llm_provider == "claude" else "none"
        )

        return {
            "answer": answer,
            "chunks": chunks,
            "model": model_name,
            "synthesis_mode": mode,
        }


# CLI usage for testing
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    api_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    if not all([api_key, index_name]):
        print("Error: Missing required environment variables.", file=sys.stderr)
        print("Required: PINECONE_API_KEY, PINECONE_INDEX_NAME")
        print("Optional: GEMINI_API_KEY or ANTHROPIC_API_KEY (for synthesis)")
        sys.exit(1)

    engine = RAGEngine(
        pinecone_api_key=api_key,
        pinecone_index_name=index_name,
        gemini_api_key=gemini_key,
        anthropic_api_key=anthropic_key,
    )

    question = sys.argv[1] if len(sys.argv) > 1 else "What are the relevant topics for MLB in 2026?"

    print(f"Question: {question}\n")

    result = engine.query(question)

    print("=" * 80)
    print("ANSWER:")
    print("=" * 80)
    print(result["answer"])

    print(f"\n{'=' * 80}")
    print(f"Retrieved {len(result['chunks'])} chunks from:")
    for chunk in result["chunks"]:
        print(f"  - {chunk['file_name']} (score: {chunk['score']:.3f})")
