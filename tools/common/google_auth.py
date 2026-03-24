#!/usr/bin/env python3
"""
Data Cleanup for RAG Agent — Google Authentication Module

Provides shared authentication for Google Drive and Sheets APIs.
Supports two auth methods (tried in order):
    1. gcloud CLI credentials (preferred — run `gcloud auth login --enable-gdrive-access`)
    2. credentials.json + token.json (fallback for service accounts or OAuth)

Pattern ported from Mandoo project (tools/common/google_auth.py).

Usage:
    from tools.common.google_auth import (
        authenticate_google_drive,
        authenticate_google_sheets,
    )
"""

import os
import sys
import time
from pathlib import Path

from tools.common.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH

# Google API scopes required by this project
# Note: drive (not drive.readonly) is needed for export of Google Docs/Sheets/Slides
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
]


def _load_credentials():
    """
    Load Google OAuth credentials. Tries gcloud first, then token.json.

    Returns:
        google.oauth2.credentials.Credentials or None
    """
    # Method 1: gcloud CLI credentials (preferred)
    creds = _load_gcloud_credentials()
    if creds:
        return creds

    # Method 2: token.json file (fallback)
    creds = _load_token_file_credentials()
    if creds:
        return creds

    print("No valid Google credentials found.", file=sys.stderr)
    print("  Option 1: Run `gcloud auth login --enable-gdrive-access`", file=sys.stderr)
    print("  Option 2: Place credentials.json + token.json in project root", file=sys.stderr)
    return None


def _load_gcloud_credentials():
    """Load credentials via `gcloud auth print-access-token`.

    Requires prior: gcloud auth login --enable-gdrive-access
    """
    import subprocess

    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "CLOUDSDK_PYTHON": "/opt/homebrew/bin/python3.13"},
        )
        token = result.stdout.strip()

        if not token or len(token) < 50:
            return None

        from google.oauth2.credentials import Credentials
        creds = Credentials(token=token)
        return creds

    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Failed to get gcloud token: {e}", file=sys.stderr)
        return None


def _load_token_file_credentials():
    """Load credentials from token.json file."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None

    if not os.path.exists(GOOGLE_TOKEN_PATH):
        return None

    try:
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH, SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(GOOGLE_TOKEN_PATH, "w") as token:
                token.write(creds.to_json())

        if creds and creds.valid:
            return creds
    except Exception:
        pass

    return None


def authenticate_google_drive():
    """
    Authenticate and return a Google Drive v3 service.

    Returns:
        googleapiclient.discovery.Resource or None
    """
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("Missing dependency: pip install google-api-python-client", file=sys.stderr)
        return None

    creds = _load_credentials()
    if not creds:
        return None

    service = build("drive", "v3", credentials=creds)
    return service


def authenticate_google_sheets():
    """
    Authenticate and return a gspread client for Google Sheets.

    Returns:
        gspread.Client or None
    """
    try:
        import gspread
    except ImportError:
        print("Missing dependency: pip install gspread", file=sys.stderr)
        return None

    creds = _load_credentials()
    if not creds:
        return None

    gc = gspread.authorize(creds)
    return gc


def retry_with_backoff(func, max_retries=3, base_delay=2):
    """
    Execute a function with exponential backoff retry logic.

    Args:
        func: Callable to execute
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (doubles each retry)

    Returns:
        The result of func()

    Raises:
        The last exception if all retries fail
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                wait_time = base_delay * (2 ** attempt)
                print(
                    f"  Attempt {attempt + 1}/{max_retries} failed, "
                    f"retrying in {wait_time}s... ({e})"
                )
                time.sleep(wait_time)
            else:
                print(
                    f"  All {max_retries} attempts failed: {e}",
                    file=sys.stderr,
                )

    raise last_exception
