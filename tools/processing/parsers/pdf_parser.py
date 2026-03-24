#!/usr/bin/env python3
"""
PDF Parser

Extracts text and metadata from PDF files.
Primary: Docling (preserves layout, tables, structure)
Fallback: PyPDF2 (basic text extraction)

Also extracts figure-heavy pages as images for multimodal embedding
via Gemini Embedding 2.

Usage:
    from tools.parsers import pdf_parser
    result = pdf_parser.parse('/path/to/file.pdf')
"""

import sys
from pathlib import Path
from typing import Dict, Any, List


def parse_with_docling(file_path: str) -> Dict[str, Any]:
    """Parse PDF using Docling (primary method)."""
    try:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(file_path)

        # Extract text and metadata
        text = result.document.export_to_markdown()

        metadata = {
            'parser': 'docling',
            'page_count': len(result.document.pages) if hasattr(result.document, 'pages') else 0,
            'has_tables': bool(result.document.tables) if hasattr(result.document, 'tables') else False
        }

        return {
            'text': text,
            'metadata': metadata,
            'raw_data': result
        }

    except ImportError:
        raise ImportError("Docling not installed. Install with: pip install docling")
    except Exception as e:
        raise Exception(f"Docling parsing failed: {e}")


def parse_with_pypdf2(file_path: str) -> Dict[str, Any]:
    """Parse PDF using PyPDF2 (fallback method)."""
    try:
        import PyPDF2

        text_parts = []

        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            page_count = len(reader.pages)

            for page_num, page in enumerate(reader.pages):
                text_parts.append(page.extract_text())

        text = '\n\n'.join(text_parts)

        metadata = {
            'parser': 'pypdf2',
            'page_count': page_count
        }

        return {
            'text': text,
            'metadata': metadata,
            'raw_data': None
        }

    except ImportError:
        raise ImportError("PyPDF2 not installed. Install with: pip install PyPDF2")
    except Exception as e:
        raise Exception(f"PyPDF2 parsing failed: {e}")


def _extract_figure_pages(file_path: str, text_per_page: Dict[int, str], min_text_threshold: int = 100) -> List[Dict]:
    """
    Identify pages with little text (likely figures/charts) and render them as images.

    Args:
        file_path: Path to PDF file
        text_per_page: Dict mapping page_number (1-based) to extracted text
        min_text_threshold: Pages with fewer chars than this are considered figure pages

    Returns:
        List of {page_number, image_bytes, mime_type} for figure-heavy pages
    """
    # Identify figure-heavy pages
    figure_pages = []
    for page_num, page_text in text_per_page.items():
        text_len = len(page_text.strip()) if page_text else 0
        if text_len < min_text_threshold:
            figure_pages.append(page_num)

    if not figure_pages:
        return []

    # Render those pages as images using pdf2image
    try:
        from pdf2image import convert_from_path
        import io

        images = []
        for page_num in figure_pages:
            try:
                page_images = convert_from_path(
                    file_path,
                    first_page=page_num,
                    last_page=page_num,
                    dpi=150,  # Balance quality vs size
                    fmt="png",
                )
                if page_images:
                    buf = io.BytesIO()
                    page_images[0].save(buf, format="PNG")
                    images.append({
                        "page_number": page_num,
                        "image_bytes": buf.getvalue(),
                        "mime_type": "image/png",
                    })
            except Exception as e:
                print(f"    Could not render page {page_num}: {e}", file=sys.stderr)
                continue

        return images

    except ImportError:
        print("    pdf2image not installed — skipping figure extraction", file=sys.stderr)
        return []
    except Exception as e:
        print(f"    Figure extraction failed: {e}", file=sys.stderr)
        return []


def parse(file_path: str) -> Dict[str, Any]:
    """
    Parse PDF file with automatic fallback.

    Also detects figure-heavy pages and renders them as images
    for multimodal embedding.

    Args:
        file_path: Path to PDF file

    Returns:
        dict: {
            'text': str,
            'metadata': dict,
            'raw_data': Any,
            'slide_images': list (figure page images, uses same key as PPTX for pipeline compatibility)
        }
    """
    if not Path(file_path).exists():
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    result = None

    # Try Docling first
    try:
        result = parse_with_docling(file_path)
    except Exception as docling_error:
        print(f"  Docling failed: {docling_error}", file=sys.stderr)
        print(f"  Falling back to PyPDF2...", file=sys.stderr)

        # Fall back to PyPDF2
        try:
            result = parse_with_pypdf2(file_path)
        except Exception as pypdf2_error:
            raise Exception(f"All PDF parsers failed. Docling: {docling_error}, PyPDF2: {pypdf2_error}")

    # Extract figure-heavy pages as images for multimodal embedding
    # Build page-level text map from PyPDF2 (even if Docling was primary)
    text_per_page = {}
    try:
        import PyPDF2
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages, 1):
                text_per_page[i] = page.extract_text() or ""
    except Exception:
        pass  # Can't get per-page text — skip figure detection

    if text_per_page:
        figure_images = _extract_figure_pages(file_path, text_per_page)
        if figure_images:
            # Use 'slide_images' key for pipeline compatibility with prepare_chunks.py
            result["slide_images"] = figure_images
            result["metadata"]["figure_page_count"] = len(figure_images)
            print(f"    Extracted {len(figure_images)} figure pages as images")

    return result


if __name__ == "__main__":
    import argparse

    parser_cli = argparse.ArgumentParser(description="Parse PDF file")
    parser_cli.add_argument("file_path", help="Path to PDF file")
    args = parser_cli.parse_args()

    result = parse(args.file_path)
    print(f"Parsed {args.file_path}")
    print(f"Text length: {len(result['text'])} characters")
    print(f"Parser used: {result['metadata'].get('parser')}")
    print(f"Pages: {result['metadata'].get('page_count', 'unknown')}")
