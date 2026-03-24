#!/usr/bin/env python3
"""
Stress Test v2 — RAG Quality Evaluation (LLM-as-Judge)

Extends the retrieval-only stress test with:
1. LLM synthesis  — Gemini Flash generates a text answer for each question
2. LLM evaluation — Gemini Flash (judge) scores the answer on 3 dimensions:
     - relevancia (0-10): does the answer address the question?
     - fidelidad (0-10): is every claim grounded in the retrieved chunks?
     - exhaustividad (0-10): does it cover all important aspects?
3. quality_score — composite metric independent of data density:
     quality_score = 0.3 × retrieval_score + 0.4 × relevance + 0.3 × faithfulness

Countries with few documents (e.g. Chile/MLC) can score well if the answer is accurate,
decoupling "how many docs exist?" from "is the answer good?".

Usage:
    PYTHONPATH=. python tools/testing/stress_test_v2.py
    PYTHONPATH=. python tools/testing/stress_test_v2.py --limit 5
    PYTHONPATH=. python tools/testing/stress_test_v2.py --skip-eval  # retrieval+synthesis only

Output:
    .tmp/stress_test_v2_results.json
"""

import json
import re
import time
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

from tools.embedding.gemini_embedder import GeminiEmbedder
from tools.ingestion.pinecone_client import PineconeClient
from tools.common.config import PINECONE_NAMESPACE, GEMINI_API_KEY

GEMINI_FLASH_MODEL = "gemini-2.5-flash"
TEXT_CAP_RETRIEVAL = 1500   # chars per chunk stored in results
TEXT_CAP_SYNTHESIS = 12000  # total context chars for synthesis
TEXT_CAP_EVAL = 3000        # total context chars for judge


# ── Test Questions ────────────────────────────────────────────────────────────

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


# ── Retrieval ─────────────────────────────────────────────────────────────────

def retrieve(embedder, index, question_data, namespace, top_k=8):
    """Retrieve chunks from Pinecone. Returns chunks with more text than v1."""
    q = question_data["q"]
    filters = question_data.get("filters", {})

    t0 = time.time()
    query_vec = embedder.embed_query(q)
    t_embed = time.time() - t0

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
            "text": meta.get("text", "")[:TEXT_CAP_RETRIEVAL],
            "slide_number": meta.get("slide_number", None),
            "chunk_index": meta.get("chunk_index", None),
        })

    scores = [c["score"] for c in chunks]
    unique_files = len(set(c["file_name"] for c in chunks))
    img_count = sum(1 for c in chunks if c["content_type"] == "slide_image")
    txt_count = len(chunks) - img_count

    filter_accuracy = 1.0
    if filters and not filters.get("$and"):
        for key, condition in filters.items():
            if isinstance(condition, dict) and "$eq" in condition:
                expected = condition["$eq"]
                matching = sum(1 for c in chunks if expected in str(c.get(key, "")))
                filter_accuracy = matching / max(len(chunks), 1)

    metrics = {
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
    }

    return chunks, metrics


# ── Synthesis ─────────────────────────────────────────────────────────────────

def synthesize(gemini_client, question, chunks):
    """
    Generate a text answer from retrieved chunks using Gemini Flash.
    Returns answer string.
    """
    if not chunks:
        return "No se encontró información relevante en la base de conocimiento."

    # Build context (cap total chars)
    context_parts = []
    total_chars = 0
    for i, chunk in enumerate(chunks):
        if chunk.get("content_type") == "slide_image":
            continue
        text = chunk.get("text", "")
        remaining = TEXT_CAP_SYNTHESIS - total_chars
        if remaining <= 100:
            break
        text = text[:remaining]
        source = chunk["file_name"]
        if chunk.get("slide_number"):
            source += f" (Slide {chunk['slide_number']})"
        context_parts.append(f"[Fuente {i+1}: {source} | Score: {chunk['score']:.3f}]\n{text}")
        total_chars += len(text)

    context = "\n\n---\n\n".join(context_parts)

    prompt = (
        "Eres un asistente experto del equipo Genova de Core Payments Corp (Mercado Pago). "
        "Responde la siguiente pregunta ÚNICAMENTE basándote en el contexto proporcionado. "
        "Reglas: (1) No inventes información. (2) Cita las fuentes. "
        "(3) Responde en el mismo idioma que la pregunta. (4) Sé conciso pero completo.\n\n"
        f"Contexto:\n{context}\n\n"
        f"Pregunta: {question}"
    )

    for attempt in range(4):
        try:
            response = gemini_client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "rate" in err.lower():
                wait = min(2 ** attempt + 2, 30)
                print(f"      Rate limit synthesis, waiting {wait}s...")
                time.sleep(wait)
            else:
                return f"[Error síntesis: {e}]"

    return "[Error: síntesis falló después de 4 reintentos]"


# ── Evaluation (LLM-as-Judge) ─────────────────────────────────────────────────

EVAL_PROMPT_TEMPLATE = """\
Eres un evaluador experto de sistemas RAG para el equipo Genova de Mercado Pago.

Tu tarea: evaluar si la respuesta generada es correcta, relevante y fiel al contexto.

PREGUNTA:
{question}

RESPUESTA GENERADA:
{answer}

CONTEXTO RECUPERADO (fragmentos usados para generar la respuesta):
{context}

---
Evalúa la respuesta en 3 dimensiones, con puntaje de 0 a 10:

- RELEVANCIA (0-10): ¿La respuesta responde directamente la pregunta?
  0 = no responde nada | 10 = responde perfectamente

- FIDELIDAD (0-10): ¿Cada afirmación de la respuesta está respaldada por el contexto?
  0 = inventa información | 10 = todo está en el contexto

- EXHAUSTIVIDAD (0-10): ¿La respuesta cubre todos los aspectos importantes de la pregunta?
  0 = muy incompleta | 10 = cubre todo lo relevante disponible

IMPORTANTE:
- Si la respuesta dice "no encontré información" pero el contexto SÍ tiene datos útiles → RELEVANCIA baja
- Si la respuesta dice "no encontré información" y el contexto realmente no tiene datos → RELEVANCIA = 5, FIDELIDAD = 10
- Si la respuesta tiene afirmaciones que NO están en el contexto → FIDELIDAD baja

Responde ÚNICAMENTE con JSON válido (sin markdown, sin texto extra):
{{"relevancia": <0-10>, "fidelidad": <0-10>, "exhaustividad": <0-10>, "justificacion": "<1 frase explicando el score principal>"}}
"""


def evaluate(gemini_client, question, answer, chunks):
    """
    Use Gemini Flash as judge to evaluate answer quality.
    Returns dict with scores 0-10 and justification.
    """
    # Build compact context for judge (cap to avoid prompt bloat)
    context_parts = []
    total = 0
    for c in chunks:
        if c.get("content_type") == "slide_image":
            continue
        text = c.get("text", "")
        if total + len(text) > TEXT_CAP_EVAL:
            text = text[:TEXT_CAP_EVAL - total]
        context_parts.append(f"[{c['file_name']}]\n{text}")
        total += len(text)
        if total >= TEXT_CAP_EVAL:
            break

    context = "\n\n".join(context_parts) if context_parts else "(sin contexto)"

    prompt = EVAL_PROMPT_TEMPLATE.format(
        question=question,
        answer=answer[:2000],  # cap answer for judge
        context=context,
    )

    for attempt in range(4):
        try:
            response = gemini_client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=prompt,
            )
            raw = response.text.strip()

            # Clean and parse JSON
            raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
            scores = json.loads(raw)

            # Validate and clamp
            for field in ("relevancia", "fidelidad", "exhaustividad"):
                val = scores.get(field, 5)
                scores[field] = max(0, min(10, int(val)))

            return scores

        except json.JSONDecodeError:
            # Try to extract JSON from response
            match = re.search(r'\{[^}]+\}', response.text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
            if attempt < 3:
                time.sleep(2)

        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "rate" in err.lower():
                wait = min(2 ** attempt + 2, 30)
                print(f"      Rate limit eval, waiting {wait}s...")
                time.sleep(wait)
            else:
                break

    # Fallback: neutral scores
    return {"relevancia": 5, "fidelidad": 5, "exhaustividad": 5, "justificacion": "[eval falhou]"}


# ── Quality Score ─────────────────────────────────────────────────────────────

def compute_quality_score(retrieval_score: float, eval_scores: dict) -> float:
    """
    Composite metric: 30% retrieval + 40% relevance + 30% faithfulness.
    Normalizes LLM scores from 0-10 to 0-1.
    """
    relevance = eval_scores.get("relevancia", 5) / 10
    faithfulness = eval_scores.get("fidelidad", 5) / 10
    return round(0.3 * retrieval_score + 0.4 * relevance + 0.3 * faithfulness, 4)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Stress Test v2 — LLM-as-Judge evaluation")
    parser.add_argument("--limit", type=int, help="Process only first N questions")
    parser.add_argument("--skip-eval", action="store_true", help="Skip LLM evaluation (retrieval+synthesis only)")
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    print("=" * 62)
    print("STRESS TEST v2 — Retrieval + Synthesis + LLM-as-Judge")
    print("=" * 62)

    embedder = GeminiEmbedder()
    client = PineconeClient()
    ns = PINECONE_NAMESPACE

    from google import genai
    gemini = genai.Client(api_key=GEMINI_API_KEY)

    stats = client.index.describe_index_stats()
    vec_count = stats.get("namespaces", {}).get(ns, {}).get("vector_count", 0)
    print(f"Index: {client.index_name} | Namespace: {ns} | Vectors: {vec_count}")
    print(f"Embedding: {embedder.model} ({embedder.dimensions} dims)")

    questions = QUESTIONS[:args.limit] if args.limit else QUESTIONS
    print(f"Questions: {len(questions)}{' (limited)' if args.limit else ''}")
    if not args.skip_eval:
        print(f"Mode: retrieval + synthesis + LLM eval (~{len(questions)*2} Gemini calls)")
    else:
        print("Mode: retrieval + synthesis (no LLM eval)")
    print()

    results = []

    for i, qdata in enumerate(questions, 1):
        cat = qdata["cat"]
        q = qdata["q"]
        print(f"  [{i:2d}/{len(questions)}] [{cat:10s}] {q[:55]}...")

        result = {
            "question_id": qdata["id"],
            "category": cat,
            "question": q,
            "filters_applied": qdata.get("filters", {}),
        }

        # ── Phase 1: Retrieval ────────────────────────────────────────
        try:
            chunks, metrics = retrieve(embedder, client.index, qdata, ns)
            result["chunks"] = chunks
            result["metrics"] = metrics
            result["retrieval_score"] = metrics["avg_score"]
            print(f"         retrieval: score={metrics['avg_score']:.3f}, chunks={metrics['chunk_count']}, files={metrics['unique_files']}")
        except Exception as e:
            print(f"         retrieval ERROR: {e}")
            result["chunks"] = []
            result["metrics"] = {"error": str(e)}
            result["retrieval_score"] = 0.0
            result["answer"] = ""
            result["eval"] = {}
            result["quality_score"] = 0.0
            results.append(result)
            continue

        time.sleep(1.0)  # Embedding rate limit

        # ── Phase 2: Synthesis ────────────────────────────────────────
        try:
            answer = synthesize(gemini, q, chunks)
            result["answer"] = answer
            preview = answer[:100].replace("\n", " ")
            print(f"         synthesis: {len(answer)} chars — \"{preview}...\"")
        except Exception as e:
            print(f"         synthesis ERROR: {e}")
            result["answer"] = f"[Error: {e}]"

        time.sleep(1.5)  # Synthesis rate limit

        # ── Phase 3: Evaluation ───────────────────────────────────────
        if not args.skip_eval:
            try:
                eval_scores = evaluate(gemini, q, result["answer"], chunks)
                result["eval"] = eval_scores
                qs = compute_quality_score(result["retrieval_score"], eval_scores)
                result["quality_score"] = qs
                r = eval_scores.get("relevancia", "?")
                f = eval_scores.get("fidelidad", "?")
                e = eval_scores.get("exhaustividad", "?")
                print(f"         eval: rel={r}/10 fid={f}/10 exh={e}/10 → quality={qs:.3f}")
            except Exception as e:
                print(f"         eval ERROR: {e}")
                result["eval"] = {}
                result["quality_score"] = result["retrieval_score"]
        else:
            result["eval"] = {}
            result["quality_score"] = result["retrieval_score"]

        results.append(result)
        time.sleep(1.5)  # Between questions
        print()

    # ── Summary ───────────────────────────────────────────────────────
    answered = [r for r in results if r.get("chunks")]
    retrieval_scores = [r["retrieval_score"] for r in answered]
    quality_scores = [r["quality_score"] for r in answered if r.get("quality_score", 0) > 0]

    avg_retrieval = sum(retrieval_scores) / max(len(retrieval_scores), 1)
    avg_quality = sum(quality_scores) / max(len(quality_scores), 1)

    # Save output
    output = {
        "test_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "index": client.index_name,
        "namespace": ns,
        "vector_count": vec_count,
        "embedding_model": embedder.model,
        "embedding_dims": embedder.dimensions,
        "llm_model": GEMINI_FLASH_MODEL,
        "eval_enabled": not args.skip_eval,
        "total_questions": len(questions),
        "avg_retrieval_score": round(avg_retrieval, 4),
        "avg_quality_score": round(avg_quality, 4),
        "results": results,
    }

    out_path = Path(".tmp/stress_test_v2_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("=" * 62)
    print("STRESS TEST v2 COMPLETE")
    print("=" * 62)
    print(f"  Questions answered : {len(answered)}/{len(results)}")
    print(f"  Avg retrieval score: {avg_retrieval:.3f}")
    if not args.skip_eval:
        print(f"  Avg quality score  : {avg_quality:.3f}  ← new metric")
    print(f"  Output: {out_path}")
    print()
    print("Next: PYTHONPATH=. python tools/testing/generate_stress_report_v2.py")


if __name__ == "__main__":
    main()
