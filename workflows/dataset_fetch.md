# Workflow: Dataset Fetch

## Objetivo
Ler o índice do dataset (Google Sheets) e produzir uma lista estruturada de arquivos com Drive IDs parseados.

## Tool
`tools/fetch/fetch_dataset.py`

## Input
- Google Sheets ID: `1gSMuR9YLn6ZfmUGJDODL0bz7jXwpQWqpT0xABa1i2Kc`
- Colunas esperadas: `Source`, `Dataset`, `URL`, `PIC`

## Output
`.tmp/dataset.json`:
```json
{
  "fetched_at": "ISO timestamp",
  "total_files": 47,
  "skipped": 4,
  "files": [
    {
      "name": "Mails mensuales Genova",
      "drive_id": "1W_SZY5hxweSh7XHgVGdvJ-T2BW0woMoMPyWUcoVbvzo",
      "url": "https://docs.google.com/document/d/.../edit",
      "source": "Documentos",
      "pic": "Marcelo Galindez",
      "drive_type": "google_doc",
      "sheet_row": 2
    }
  ]
}
```

## URL Parsing
Formatos suportados:
- `https://docs.google.com/document/d/{ID}/...` → google_doc
- `https://docs.google.com/spreadsheets/d/{ID}/...` → google_sheet
- `https://docs.google.com/presentation/d/{ID}/...` → google_slides
- `https://drive.google.com/file/d/{ID}/...` → drive_file
- `https://drive.google.com/drive/folders/{ID}` → folder

URLs não-Google (Miro, Trello, etc.) são skipped com warning.

## Comando
```bash
PYTHONPATH=. python tools/fetch/fetch_dataset.py
```
