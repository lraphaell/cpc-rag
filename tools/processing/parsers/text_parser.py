#!/usr/bin/env python3
"""
Text Parser

Extracts text from plain text files with encoding detection.

Usage:
    from tools.parsers import text_parser
    result = text_parser.parse('/path/to/file.txt')
"""

from pathlib import Path
from typing import Dict, Any


def detect_encoding(file_path: str) -> str:
    """Detect file encoding using chardet."""
    try:
        import chardet

        with open(file_path, 'rb') as f:
            raw_data = f.read()
            result = chardet.detect(raw_data)
            return result['encoding'] or 'utf-8'

    except ImportError:
        # Fallback to utf-8 if chardet not available
        return 'utf-8'
    except Exception:
        return 'utf-8'


def parse(file_path: str) -> Dict[str, Any]:
    """
    Parse text file with automatic encoding detection.

    Args:
        file_path: Path to text file

    Returns:
        dict: {
            'text': str,
            'metadata': dict,
            'raw_data': None
        }
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Detect encoding
    encoding = detect_encoding(file_path)

    # Read file
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            text = f.read()
    except UnicodeDecodeError:
        # Fallback to utf-8 with error handling
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        encoding = 'utf-8 (with errors ignored)'

    # Count lines
    line_count = text.count('\n') + 1

    metadata = {
        'parser': 'text',
        'type': 'TXT',
        'encoding': encoding,
        'line_count': line_count,
        'character_count': len(text)
    }

    return {
        'text': text,
        'metadata': metadata,
        'raw_data': None
    }


if __name__ == "__main__":
    import argparse

    parser_cli = argparse.ArgumentParser(description="Parse text file")
    parser_cli.add_argument("file_path", help="Path to text file")
    args = parser_cli.parse_args()

    result = parse(args.file_path)
    print(f"Parsed {args.file_path}")
    print(f"Encoding: {result['metadata']['encoding']}")
    print(f"Lines: {result['metadata']['line_count']}")
    print(f"Characters: {result['metadata']['character_count']}")
