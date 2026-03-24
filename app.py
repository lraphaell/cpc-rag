#!/usr/bin/env python3
"""
Genova RAG Chat — Streamlit frontend for the Genova knowledge base.

Queries Pinecone vector database and synthesizes answers using Google Gemini (or Claude).
Supports metadata filters (country, team, bandera, fecha) via sidebar.

Usage:
    PYTHONPATH=. streamlit run app.py
"""

import os
import sys
import streamlit as st
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path for imports
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tools.query.query_builder import build_query

# Must be the first Streamlit command — required before any other st.* call
st.set_page_config(
    page_title="Genova RAG Chat",
    page_icon="🔍",
    layout="wide",
)

# Also support Streamlit Cloud secrets
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY") or st.secrets.get("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "genova-v2")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "genova-prod")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or st.secrets.get("ANTHROPIC_API_KEY", "")

# ── Password protection ──────────────────────────────────────────────
APP_PASSWORD = os.getenv("APP_PASSWORD") or st.secrets.get("APP_PASSWORD", "")
if APP_PASSWORD:
    if not st.session_state.get("authenticated"):
        st.title("Genova RAG")
        pwd = st.text_input("Password", type="password")
        if st.button("Entrar"):
            if pwd == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Senha incorreta")
        st.stop()

# ── Valid filter values ──────────────────────────────────────────────
COUNTRIES = ["Todos", "MLA", "MLB", "MLM", "MLU", "MLC", "MCO", "Corp"]
TEAMS = [
    "Todos", "Genova", "Relacionamiento con las banderas", "Negocio cross",
    "Bari", "Mejora Continua y Planning", "Scheme enablers", "Optimus", "X Countries",
]
BANDERAS = [
    "Todas", "Visa", "Mastercard", "American Express", "Cabal",
    "Elo", "Hipercard", "Carnet", "Naranja", "Otra",
]


@st.cache_resource
def get_rag_engine():
    """Initialize RAG engine (cached across sessions)."""
    try:
        from tools.query.rag_engine import RAGEngine
        return RAGEngine(
            pinecone_api_key=PINECONE_API_KEY,
            pinecone_index_name=PINECONE_INDEX_NAME,
            gemini_api_key=GEMINI_API_KEY,
            anthropic_api_key=ANTHROPIC_API_KEY,
            namespace=PINECONE_NAMESPACE,
        )
    except Exception as e:
        st.error(f"No se pudo conectar al RAG engine: {e}")
        return None


@st.cache_resource
def get_pinecone_client():
    """Initialize Pinecone client for filtered queries (cached)."""
    try:
        from tools.ingestion.pinecone_client import PineconeClient
        return PineconeClient()
    except Exception as e:
        st.error(f"No se pudo conectar a Pinecone: {e}")
        return None


from tools.common.utils import is_tabular_text as is_tabular_chunk


def diversify_chunks(chunks, max_per_file=2):
    """Filter tabular data and ensure diversity by limiting chunks per file."""
    # First pass: remove raw tabular chunks
    filtered = [c for c in chunks if not is_tabular_chunk(c.get("text", ""))]

    # If filtering removed everything, fall back to original
    if not filtered:
        filtered = chunks

    # Second pass: limit per file for diversity
    file_counts = {}
    diverse = []
    for c in filtered:
        fname = c.get("file_name", "")
        file_counts[fname] = file_counts.get(fname, 0) + 1
        if file_counts[fname] <= max_per_file:
            diverse.append(c)
    return diverse


def query_with_filters(question, filters_dict, top_k, engine, boost_file_ids=None):
    """Query Pinecone with filters, then synthesize with LLM."""
    client = get_pinecone_client()
    if not client or not engine:
        return {"answer": "Error: No se pudo conectar a los servicios. Reinicia la app.", "chunks": [], "synthesis_mode": "error"}

    # Retrieve more than needed, then filter and diversify
    fetch_k = min(top_k * 5, 50)
    raw_chunks = client.query(
        text=question,
        top_k=fetch_k,
        namespace=PINECONE_NAMESPACE,
        filters=filters_dict,
    )

    # Boost: fetch chunks from key documents that embedding might miss
    if boost_file_ids:
        seen_ids = set(c.get("id", "") for c in raw_chunks)
        for fid in boost_file_ids:
            boost_results = client.query(
                text=question,
                top_k=3,
                namespace=PINECONE_NAMESPACE,
                filters={"drive_file_id": fid},
            )
            for br in boost_results:
                if br.get("id", "") not in seen_ids:
                    raw_chunks.append(br)
                    seen_ids.add(br.get("id", ""))

    # Filter tabular data + diversify (max 2 per file)
    diverse = diversify_chunks(raw_chunks, max_per_file=2)[:top_k]

    # Format chunks for RAGEngine synthesize()
    formatted_chunks = []
    for c in diverse:
        formatted_chunks.append({
            "id": c.get("id", ""),
            "score": float(c.get("score", 0)),
            "text": c.get("text", ""),
            "file_name": c.get("file_name", "Unknown"),
            "file_type": c.get("file_type", ""),
            "sheet_name": c.get("sheet_name", ""),
            "slide_number": c.get("slide_number", ""),
            "chunk_index": c.get("chunk_index", ""),
            "country": c.get("country", ""),
            "bandera": c.get("bandera", ""),
            "team": c.get("team", ""),
            "fecha": c.get("fecha", ""),
        })

    # Synthesize answer
    if engine.client:
        answer = engine.synthesize(question, formatted_chunks)
        mode = "claude"
    else:
        if formatted_chunks:
            parts = []
            for i, chunk in enumerate(formatted_chunks[:5]):
                text = chunk["text"][:500]
                parts.append(f"**{chunk['file_name']}** (score: {chunk['score']:.3f})\n\n{text}...")
            answer = "\n\n---\n\n".join(parts)
        else:
            answer = "No se encontraron resultados relevantes."
        mode = "retrieval_only"

    return {"answer": answer, "chunks": formatted_chunks, "synthesis_mode": mode}


# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Genova Knowledge Base")
    st.caption("Chat inteligente sobre la base de documentos del equipo Genova")

    st.divider()
    st.subheader("Filtros")

    filter_country = st.selectbox("Country", COUNTRIES, index=0)
    filter_team = st.selectbox("Team", TEAMS, index=0)
    filter_bandera = st.selectbox("Bandera", BANDERAS, index=0)
    filter_fecha = st.text_input("Fecha (YYYY-QN)", placeholder="ej: 2025-Q1")
    top_k = st.slider("Resultados a buscar", min_value=3, max_value=20, value=8)

    st.divider()

    # Status indicators
    has_gemini = bool(GEMINI_API_KEY and GEMINI_API_KEY not in ("", "your_gemini_key_here"))
    has_claude = bool(ANTHROPIC_API_KEY and ANTHROPIC_API_KEY not in ("", "your_anthropic_key_here"))
    if has_gemini:
        st.success("LLM: Gemini conectado")
    elif has_claude:
        st.success("LLM: Claude conectado")
    else:
        st.warning("LLM: No configurado (modo retrieval-only)")

    st.info(f"Pinecone: `{PINECONE_NAMESPACE}`")

    st.divider()
    st.caption(f"Pinecone `{PINECONE_NAMESPACE}` | Gemini 2.5 Flash")

# ── Main chat area ───────────────────────────────────────────────────
st.title("Genova RAG Chat")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and "chunks" in message:
            with st.expander(f"Ver fuentes ({len(message['chunks'])} chunks)"):
                for i, chunk in enumerate(message["chunks"]):
                    score = chunk.get("score", 0)
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**{chunk['file_name']}**")
                    with col2:
                        st.caption(f"score: {score:.3f}")
                    meta_parts = []
                    if chunk.get("country"):
                        meta_parts.append(f"country={chunk['country']}")
                    if chunk.get("bandera"):
                        meta_parts.append(f"bandera={chunk['bandera']}")
                    if chunk.get("fecha"):
                        meta_parts.append(f"fecha={chunk['fecha']}")
                    if meta_parts:
                        st.caption(" | ".join(meta_parts))
                    st.text(chunk["text"][:300] + "..." if len(chunk.get("text", "")) > 300 else chunk.get("text", ""))
                    if i < len(message["chunks"]) - 1:
                        st.divider()

# Chat input
if prompt := st.chat_input("Haceme una pregunta sobre la base de conocimiento..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Build query with filters
    query_text, pinecone_filters, k, boost_file_ids = build_query(
        question=prompt,
        country=filter_country,
        team=filter_team,
        bandera=filter_bandera,
        fecha=filter_fecha,
        top_k=top_k,
    )

    # Show active filters
    if pinecone_filters:
        filter_display = ", ".join(f"{k}: {v}" for k, v in pinecone_filters.items())
        st.caption(f"Filtros activos: {filter_display}")

    # Query and respond
    with st.chat_message("assistant"):
        with st.spinner("Buscando en la base de conocimiento..."):
            try:
                engine = get_rag_engine()
                result = query_with_filters(query_text, pinecone_filters, k, engine, boost_file_ids)

                st.markdown(result["answer"])

                # Show sources
                chunks = result.get("chunks", [])
                if chunks:
                    with st.expander(f"Ver fuentes ({len(chunks)} chunks)"):
                        for i, chunk in enumerate(chunks):
                            score = chunk.get("score", 0)
                            col1, col2 = st.columns([3, 1])
                            with col1:
                                st.markdown(f"**{chunk['file_name']}**")
                            with col2:
                                st.caption(f"score: {score:.3f}")
                            meta_parts = []
                            if chunk.get("country"):
                                meta_parts.append(f"country={chunk['country']}")
                            if chunk.get("bandera"):
                                meta_parts.append(f"bandera={chunk['bandera']}")
                            if chunk.get("fecha"):
                                meta_parts.append(f"fecha={chunk['fecha']}")
                            if meta_parts:
                                st.caption(" | ".join(meta_parts))
                            st.text(chunk["text"][:300] + "..." if len(chunk.get("text", "")) > 300 else chunk.get("text", ""))
                            if i < len(chunks) - 1:
                                st.divider()

                # Save to history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["answer"],
                    "chunks": chunks,
                })

            except Exception as e:
                error_msg = f"Error: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg,
                })
