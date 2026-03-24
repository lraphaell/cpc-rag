"""
Document Parsers Module

Provides parsers for different file formats:
- PDF: pdf_parser
- Office: office_parser (DOCX, PPTX)
- Spreadsheet: spreadsheet_parser (XLSX, CSV)
- Text: text_parser (TXT)
"""

from pathlib import Path

def get_parser(file_type: str):
    """
    Get appropriate parser for file type.

    Args:
        file_type: File type (PDF, DOCX, PPTX, XLSX, CSV, TXT)

    Returns:
        Parser module
    """
    file_type = file_type.upper()

    if file_type == 'PDF':
        from . import pdf_parser
        return pdf_parser
    elif file_type in ['DOCX', 'PPTX']:
        from . import office_parser
        return office_parser
    elif file_type in ['XLSX', 'CSV']:
        from . import spreadsheet_parser
        return spreadsheet_parser
    elif file_type == 'TXT':
        from . import text_parser
        return text_parser
    else:
        raise ValueError(f"Unsupported file type: {file_type}")
