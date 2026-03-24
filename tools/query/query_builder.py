#!/usr/bin/env python3
"""
Query Builder — Transforms user question + UI filters into Pinecone query.

Builds metadata filters from sidebar selections and detects implicit
keywords in the question text to add filters automatically.

Usage:
    from tools.query.query_builder import build_query

    query_text, filters, top_k = build_query(
        question="Fee de bandera Visa en Brasil",
        country="Todos",
        team="Todos",
        bandera="Todas",
        fecha=""
    )
"""

import re
from typing import Dict, List, Optional, Tuple

# Country detection patterns (question text -> country code)
COUNTRY_KEYWORDS = {
    "MLA": re.compile(r"\bMLA\b|Argentina", re.IGNORECASE),
    "MLB": re.compile(r"\bMLB\b|Brasil|Brazil", re.IGNORECASE),
    "MLM": re.compile(r"\bMLM\b|M[eé]xico", re.IGNORECASE),
    "MLU": re.compile(r"\bMLU\b|Uruguay", re.IGNORECASE),
    "MLC": re.compile(r"\bMLC\b|Chile", re.IGNORECASE),
    "MCO": re.compile(r"\bMCO\b|Colombia", re.IGNORECASE),
}

BANDERA_KEYWORDS = {
    "Visa": re.compile(r"\bVisa\b", re.IGNORECASE),
    "Mastercard": re.compile(r"\bMastercard\b|\bMC\b", re.IGNORECASE),
    "American Express": re.compile(r"\bAmex\b|American\s*Express", re.IGNORECASE),
    "Elo": re.compile(r"\bElo\b|\bELO\b"),
    "Cabal": re.compile(r"\bCabal\b", re.IGNORECASE),
}


def detect_implicit_filters(question: str) -> Dict[str, str]:
    """Detect metadata values mentioned in the question text."""
    detected = {}

    # Detect country
    countries = [code for code, pattern in COUNTRY_KEYWORDS.items() if pattern.search(question)]
    if len(countries) == 1:
        detected["country"] = countries[0]

    # Detect bandera
    banderas = [name for name, pattern in BANDERA_KEYWORDS.items() if pattern.search(question)]
    if len(banderas) == 1:
        detected["bandera"] = banderas[0]

    return detected


def build_query(
    question: str,
    country: str = "Todos",
    team: str = "Todos",
    bandera: str = "Todas",
    fecha: str = "",
    top_k: int = 8,
) -> Tuple[str, Optional[Dict], int]:
    """
    Build Pinecone query from user question and sidebar filters.

    Args:
        question: User's natural language question
        country: Selected country filter (or "Todos")
        team: Selected team filter (or "Todos")
        bandera: Selected bandera filter (or "Todas")
        fecha: Fecha filter text (e.g., "2025-Q1") or empty
        top_k: Number of results to retrieve

    Returns:
        Tuple of (query_text, pinecone_filters_dict_or_None, top_k)
    """
    filters = {}

    # Explicit filters from sidebar (simple equality for Pinecone Inference API)
    if country and country != "Todos":
        filters["country"] = country
    if team and team != "Todos":
        filters["team"] = team
    if bandera and bandera != "Todas":
        filters["bandera"] = bandera
    if fecha and fecha.strip():
        filters["fecha"] = fecha.strip()

    # Implicit filters from question text (only if not already filtered)
    implicit = detect_implicit_filters(question)
    if "country" not in filters and "country" in implicit:
        filters["country"] = implicit["country"]
    if "bandera" not in filters and "bandera" in implicit:
        filters["bandera"] = implicit["bandera"]

    pinecone_filters = filters if filters else None

    # Detect if this is a broad/overview question that needs key documents
    boost_file_ids = detect_boost_files(question)

    return question, pinecone_filters, top_k, boost_file_ids


# Key documents that contain overview/summary content.
# These are boosted when the question is about general topics.
KEY_DOCS = {
    "mails_mensuales": "1W_SZY5hxweSh7XHgVGdvJ-T2BW0woMoMPyWUcoVbvzo",
    "roadmap_2026": "1YlvAYmRZ6QaLj4teyYPBgTwl8RlnQ_jHc7g-y-S5_Cs",
}

# Patterns that indicate a broad/overview question
OVERVIEW_PATTERNS = re.compile(
    r"principa|proyecto|resumen|resultado|overview|roadmap|entrega|avance|"
    r"logro|hito|milestone|cierre|monthly|site|general",
    re.IGNORECASE,
)


def detect_boost_files(question: str) -> List[str]:
    """Return file IDs of key docs to boost when question is about overview topics."""
    if OVERVIEW_PATTERNS.search(question):
        return list(KEY_DOCS.values())
    return []
