#!/usr/bin/env python3
"""
Shared utility functions used across multiple tools.

Centralizes logic that was previously duplicated in app.py,
prepare_chunks.py, process_and_ingest.py, remove_tabular_chunks.py.
"""

TABULAR_DIGIT_THRESHOLD = 0.12
TABULAR_MIN_LENGTH = 100


def is_tabular_text(text, min_len=TABULAR_MIN_LENGTH, threshold=TABULAR_DIGIT_THRESHOLD):
    """
    Check if text is raw tabular/transactional data (high digit ratio).

    Args:
        text: Text to check
        min_len: Minimum text length to evaluate (shorter texts are not tabular)
        threshold: Digit ratio above which text is considered tabular

    Returns:
        bool: True if text is likely raw spreadsheet/transactional data
    """
    if not text or len(text) < min_len:
        return False
    return sum(1 for ch in text if ch.isdigit()) / len(text) > threshold
