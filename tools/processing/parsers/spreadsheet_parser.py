#!/usr/bin/env python3
"""
Spreadsheet Parser

Extracts data and metadata from spreadsheet files.
- XLSX: pandas with openpyxl
- CSV: pandas

Usage:
    from tools.parsers import spreadsheet_parser
    result = spreadsheet_parser.parse('/path/to/file.xlsx')
"""

from pathlib import Path
from typing import Dict, Any
import pandas as pd


def parse_xlsx(file_path: str) -> Dict[str, Any]:
    """Parse Excel file (.xlsx)."""
    try:
        # Read all sheets
        excel_file = pd.ExcelFile(file_path, engine='openpyxl')
        sheet_names = excel_file.sheet_names

        sheets_data = {}
        all_text = []

        for sheet_name in sheet_names:
            df = pd.read_excel(file_path, sheet_name=sheet_name, engine='openpyxl')
            sheets_data[sheet_name] = df

            # Convert to text representation
            # Replace NaN with empty string to avoid "NaN" text in output
            df_clean = df.fillna('')
            sheet_text = f"=== Sheet: {sheet_name} ===\n"
            sheet_text += df_clean.to_string(index=False)
            all_text.append(sheet_text)

        text = '\n\n'.join(all_text)

        metadata = {
            'parser': 'pandas-openpyxl',
            'type': 'XLSX',
            'sheet_count': len(sheet_names),
            'sheet_names': sheet_names,
            'total_rows': sum(len(df) for df in sheets_data.values()),
            'total_columns': sum(len(df.columns) for df in sheets_data.values())
        }

        return {
            'text': text,
            'metadata': metadata,
            'raw_data': sheets_data
        }

    except ImportError:
        raise ImportError("Required packages not installed. Install with: pip install pandas openpyxl")
    except Exception as e:
        raise Exception(f"XLSX parsing failed: {e}")


def parse_csv(file_path: str) -> Dict[str, Any]:
    """Parse CSV file."""
    try:
        df = pd.read_csv(file_path)

        # Convert to text (replace NaN with empty string)
        df_clean = df.fillna('')
        text = df_clean.to_string(index=False)

        metadata = {
            'parser': 'pandas',
            'type': 'CSV',
            'row_count': len(df),
            'column_count': len(df.columns),
            'columns': list(df.columns)
        }

        return {
            'text': text,
            'metadata': metadata,
            'raw_data': df
        }

    except ImportError:
        raise ImportError("pandas not installed. Install with: pip install pandas")
    except Exception as e:
        raise Exception(f"CSV parsing failed: {e}")


def parse(file_path: str) -> Dict[str, Any]:
    """
    Parse spreadsheet file (auto-detect type).

    Args:
        file_path: Path to XLSX or CSV file

    Returns:
        dict: {
            'text': str,
            'metadata': dict,
            'raw_data': Any (DataFrame or dict of DataFrames)
        }
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    if suffix == '.xlsx':
        return parse_xlsx(file_path)
    elif suffix == '.csv':
        return parse_csv(file_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Expected .xlsx or .csv")


if __name__ == "__main__":
    import argparse

    parser_cli = argparse.ArgumentParser(description="Parse spreadsheet file")
    parser_cli.add_argument("file_path", help="Path to XLSX or CSV file")
    args = parser_cli.parse_args()

    result = parse(args.file_path)
    print(f"Parsed {args.file_path}")
    print(f"Type: {result['metadata']['type']}")
    print(f"Text length: {len(result['text'])} characters")
    if result['metadata']['type'] == 'XLSX':
        print(f"Sheets: {result['metadata']['sheet_count']}")
        print(f"Total rows: {result['metadata']['total_rows']}")
    else:
        print(f"Rows: {result['metadata']['row_count']}")
        print(f"Columns: {result['metadata']['column_count']}")
