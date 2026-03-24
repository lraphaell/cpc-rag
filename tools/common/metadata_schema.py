#!/usr/bin/env python3
"""
Centralized metadata schema — single source of truth for valid values.

All tools that validate, extract, or filter by metadata should import
from here instead of defining their own lists.
"""

import re

# ── Valid metadata values ────────────────────────────────────────────
VALID_COUNTRIES = {"MLA", "MLB", "MLM", "MLU", "MLC", "MCO", "Corp"}
VALID_TEAMS = {
    "Genova",
    "Relacionamiento con las banderas",
    "Negocio cross",
    "Bari",
    "Mejora Continua y Planning",
    "Scheme enablers",
    "Optimus",
    "X Countries",
}
VALID_BANDERAS = {
    "Visa", "Mastercard", "American Express", "Cabal",
    "Elo", "Hipercard", "Carnet", "Naranja", "Otra",
}
FECHA_REGEX = re.compile(r"^\d{4}-Q[1-4]$")

# ── Detection patterns (for auto-tagging and query builder) ─────────
COUNTRY_PATTERNS = {
    "MLA": re.compile(r"\bMLA\b|Argentina", re.IGNORECASE),
    "MLB": re.compile(r"\bMLB\b|Brasil|Brazil", re.IGNORECASE),
    "MLM": re.compile(r"\bMLM\b|M[eé]xico|PROSA", re.IGNORECASE),
    "MLU": re.compile(r"\bMLU\b|Uruguay", re.IGNORECASE),
    "MLC": re.compile(r"\bMLC\b|Chile", re.IGNORECASE),
    "MCO": re.compile(r"\bMCO\b|Colombia", re.IGNORECASE),
}

BANDERA_PATTERNS = {
    "Visa": re.compile(r"\bVisa\b|VISA\b", re.IGNORECASE),
    "Mastercard": re.compile(r"\bMastercard\b|\bMC\b(?!\s*&)", re.IGNORECASE),
    "American Express": re.compile(r"\bAmex\b|American\s*Express", re.IGNORECASE),
    "Elo": re.compile(r"\bElo\b|\bELO\b"),
    "Cabal": re.compile(r"\bCabal\b", re.IGNORECASE),
    "Hipercard": re.compile(r"\bHipercard\b", re.IGNORECASE),
    "Carnet": re.compile(r"\bCarnet\b", re.IGNORECASE),
    "Naranja": re.compile(r"\bNaranja\b", re.IGNORECASE),
}
