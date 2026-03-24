#!/usr/bin/env python3
"""
Stress Test — RAG Retrieval

Runs 30 test queries against Pinecone and collects chunks + scores.
Does NOT call any LLM API — synthesis is done by Claude agent reading the results.

Usage:
    PYTHONPATH=. python tools/testing/stress_test_rag.py

Output:
    .tmp/stress_test_retrieval.json — raw retrieval results for all 30 questions
"""

import json
import time
import sys
from pathlib import Path
from tools.embedding.gemini_embedder import GeminiEmbedder
from tools.ingestion.pinecone_client import PineconeClient
from tools.common.config import PINECONE_NAMESPACE

# ── Test Questions ──────────────────────────────────────────────────

QUESTIONS = [
    # Cat 1: Simple & Direct (5)
    {"id": 1, "cat": "simple", "q": "¿Qué es el equipo Genova y cuál es su misión?", "filters": {}},
    {"id": 2, "cat": "simple", "q": "¿Cuál es el plan de Optimus para 2026?", "filters": {}},
    {"id": 3, "cat": "simple", "q": "¿Qué es la tokenización y cuál es el plan para 2026?", "filters": {}},
    {"id": 4, "cat": "simple", "q": "¿Cómo funciona el fee de bandera?", "filters": {}},
    {"id": 5, "cat": "simple", "q": "¿Qué es el proyecto Elo en Brasil?", "filters": {}},

    # Cat 2: Country Filters (5)
    {"id": 6, "cat": "country", "q": "¿Cuáles son los proyectos activos en Argentina?", "filters": {"country": {"$eq": "MLA"}}},
    {"id": 7, "cat": "country", "q": "¿Qué iniciativas hay en México?", "filters": {"country": {"$eq": "MLM"}}},
    {"id": 8, "cat": "country", "q": "¿Cuál es la situación de Colombia?", "filters": {"country": {"$eq": "MCO"}}},
    {"id": 9, "cat": "country", "q": "¿Qué proyectos tiene Brasil en 2025?", "filters": {"country": {"$eq": "MLB"}}},
    {"id": 10, "cat": "country", "q": "¿Qué actividades hay en Chile?", "filters": {"country": {"$eq": "MLC"}}},

    # Cat 3: Bandera Filters (4)
    {"id": 11, "cat": "bandera", "q": "¿Cuál es el estado del fee de bandera Mastercard?", "filters": {"bandera": {"$eq": "Mastercard"}}},
    {"id": 12, "cat": "bandera", "q": "¿Qué acuerdos hay con Visa?", "filters": {"bandera": {"$eq": "Visa"}}},
    {"id": 13, "cat": "bandera", "q": "¿Cuál es el plan con American Express?", "filters": {"bandera": {"$eq": "American Express"}}},
    {"id": 14, "cat": "bandera", "q": "¿Hay iniciativas con Elo?", "filters": {"bandera": {"$eq": "Elo"}}},

    # Cat 4: Team Filters (3)
    {"id": 15, "cat": "team", "q": "¿Qué está haciendo el equipo Optimus?", "filters": {"team": {"$eq": "Optimus"}}},
    {"id": 16, "cat": "team", "q": "¿Cuáles son las actividades de Mejora Continua?", "filters": {"team": {"$eq": "Mejora Continua y Planning"}}},
    {"id": 17, "cat": "team", "q": "¿Qué temas se discutieron en los workshops con banderas?", "filters": {"team": {"$eq": "Relacionamiento con las banderas"}}},

    # Cat 5: Complex Multi-dimension (5)
    {"id": 18, "cat": "complex", "q": "¿Cuál fue el resultado del tradeoff de Genova en Q4 2025?", "filters": {}},
    {"id": 19, "cat": "complex", "q": "¿Cuáles son los fees de Mastercard en Argentina para emisión?",
     "filters": {"$and": [{"country": {"$eq": "MLA"}}, {"bandera": {"$eq": "Mastercard"}}]}},
    {"id": 20, "cat": "complex", "q": "¿Qué avances hubo en tokenización en Brasil?", "filters": {"country": {"$eq": "MLB"}}},
    {"id": 21, "cat": "complex", "q": "¿Cuál es el roadmap de Genova para 2026?", "filters": {}},
    {"id": 22, "cat": "complex", "q": "¿Qué temas se discutieron en el workshop de Visa en Colombia?",
     "filters": {"$and": [{"country": {"$eq": "MCO"}}, {"bandera": {"$eq": "Visa"}}]}},

    # Cat 6: Portuguese (3)
    {"id": 23, "cat": "portuguese", "q": "Qual é o projeto Elo no Brasil e qual o status atual?", "filters": {"country": {"$eq": "MLB"}}},
    {"id": 24, "cat": "portuguese", "q": "Como funciona o processo de fee de bandeira no Mercado Pago?", "filters": {}},
    {"id": 25, "cat": "portuguese", "q": "Quais são os principais temas do onboarding Genova?", "filters": {}},

    # Cat 7: Edge Cases (5)
    {"id": 26, "cat": "edge", "q": "¿Cuál es la diferencia entre fee de bandera de adquirencia y emisión?", "filters": {}},
    {"id": 27, "cat": "edge", "q": "¿Qué cambios hubo en los fees entre 2024 y 2025?", "filters": {}},
    {"id": 28, "cat": "edge", "q": "Resúmeme los principales KPIs del equipo Genova", "filters": {}},
    {"id": 29, "cat": "edge", "q": "¿Hay información sobre Uruguay?", "filters": {"country": {"$eq": "MLU"}}},
    {"id": 30, "cat": "edge", "q": "What are the main payment processing challenges in Latin America?", "filters": {}},
]


def run_retrieval(embedder, index, question_data, namespace, top_k=8):
    """Run a single retrieval query and return results."""
    q = question_data["q"]
    filters = question_data.get("filters", {})

    t0 = time.time()

    # Embed query
    query_vec = embedder.embed_query(q)
    t_embed = time.time() - t0

    # Search Pinecone
    kwargs = {
        "vector": query_vec,
        "top_k": top_k,
        "namespace": namespace,
        "include_metadata": True,
    }
    if filters:
        kwargs["filter"] = filters

    response = index.query(**kwargs)
    t_search = time.time() - t0

    # Process results
    chunks = []
    for match in response.get("matches", []):
        meta = match.get("metadata", {})
        chunks.append({
            "id": match["id"],
            "score": round(match.get("score", 0), 4),
            "file_name": meta.get("file_name", ""),
            "content_type": meta.get("content_type", "text"),
            "country": meta.get("country", ""),
            "bandera": meta.get("bandera", ""),
            "team": meta.get("team", ""),
            "fecha": meta.get("fecha", ""),
            "text": meta.get("text", "")[:500],  # Cap for report
            "slide_number": meta.get("slide_number", None),
            "chunk_index": meta.get("chunk_index", None),
        })

    # Metrics
    scores = [c["score"] for c in chunks]
    unique_files = len(set(c["file_name"] for c in chunks))
    img_count = sum(1 for c in chunks if c["content_type"] == "slide_image")
    txt_count = sum(1 for c in chunks if c["content_type"] != "slide_image")

    # Filter accuracy: check if returned chunks match requested filters
    filter_accuracy = 1.0
    if filters and not filters.get("$and"):
        for key, condition in filters.items():
            if isinstance(condition, dict) and "$eq" in condition:
                expected = condition["$eq"]
                matching = sum(1 for c in chunks if expected in str(c.get(key, "")))
                filter_accuracy = matching / max(len(chunks), 1)

    return {
        "question_id": question_data["id"],
        "category": question_data["cat"],
        "question": q,
        "filters_applied": filters,
        "chunks": chunks,
        "metrics": {
            "avg_score": round(sum(scores) / max(len(scores), 1), 4),
            "top_score": round(max(scores) if scores else 0, 4),
            "min_score": round(min(scores) if scores else 0, 4),
            "chunk_count": len(chunks),
            "unique_files": unique_files,
            "text_chunks": txt_count,
            "image_chunks": img_count,
            "filter_accuracy": round(filter_accuracy, 2),
            "latency_embed_s": round(t_embed, 2),
            "latency_total_s": round(t_search, 2),
        },
    }


def main():
    print("=" * 60)
    print("STRESS TEST — RAG Retrieval (30 questions)")
    print("=" * 60)

    embedder = GeminiEmbedder()
    client = PineconeClient()
    ns = PINECONE_NAMESPACE

    stats = client.index.describe_index_stats()
    vec_count = stats.get("namespaces", {}).get(ns, {}).get("vector_count", 0)
    print(f"Index: {client.index_name} | Namespace: {ns} | Vectors: {vec_count}")
    print(f"Embedding: {embedder.model} ({embedder.dimensions} dims)")
    print(f"Questions: {len(QUESTIONS)}")
    print()

    results = []
    for i, qdata in enumerate(QUESTIONS, 1):
        cat = qdata["cat"]
        q = qdata["q"][:60]
        print(f"  [{i:2d}/30] [{cat:10s}] {q}...", end=" ", flush=True)

        try:
            result = run_retrieval(embedder, client.index, qdata, ns)
            results.append(result)
            m = result["metrics"]
            print(f"OK (score={m['avg_score']:.3f}, chunks={m['chunk_count']}, files={m['unique_files']})")
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                "question_id": qdata["id"],
                "category": qdata["cat"],
                "question": qdata["q"],
                "filters_applied": qdata.get("filters", {}),
                "chunks": [],
                "metrics": {"error": str(e)},
            })

        time.sleep(1.5)  # Rate limit protection

    # Save results
    output = {
        "test_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "index": client.index_name,
        "namespace": ns,
        "vector_count": vec_count,
        "embedding_model": embedder.model,
        "embedding_dims": embedder.dimensions,
        "total_questions": len(QUESTIONS),
        "results": results,
    }

    out_path = Path(".tmp/stress_test_retrieval.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Summary
    ok = [r for r in results if r["chunks"]]
    avg_scores = [r["metrics"]["avg_score"] for r in ok if "avg_score" in r["metrics"]]

    print(f"\n{'='*60}")
    print(f"RETRIEVAL COMPLETE")
    print(f"{'='*60}")
    print(f"Questions answered: {len(ok)}/{len(results)}")
    print(f"Avg retrieval score: {sum(avg_scores)/max(len(avg_scores),1):.3f}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
