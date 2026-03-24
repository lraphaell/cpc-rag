# Workflow: Change Detection

## Objetivo
Comparar os arquivos do dataset contra o estado local (`state.json`) para identificar o que mudou desde a última execução.

## Tool
`tools/state/detect_changes.py`

## Input
- `.tmp/dataset.json` (do fetch_dataset.py)
- `.tmp/state.json` (do run anterior, ou vazio na primeira execução)

## Output
`.tmp/change_manifest.json`:
```json
{
  "detected_at": "ISO timestamp",
  "total_in_dataset": 47,
  "changes": [
    {"action": "add", "file_info": {"drive_id": "...", "name": "...", "modified_time": "..."}},
    {"action": "update", "file_info": {"drive_id": "...", "name": "...", "modified_time": "..."}},
    {"action": "delete", "file_info": {"drive_id": "...", "name": "..."}}
  ]
}
```

## Lógica de Detecção

| Situação | Ação |
|----------|------|
| Drive ID não existe no state.json | `add` — arquivo novo |
| Drive `modifiedTime` > state `modified_time` | `update` — arquivo modificado |
| Drive ID está no state mas não no dataset | `delete` — arquivo removido |
| Drive `modifiedTime` == state `modified_time` | skip — sem alteração |

## State File (`.tmp/state.json`)
```json
{
  "last_run": "ISO timestamp",
  "files": {
    "drive_id_abc": {
      "name": "documento.pdf",
      "modified_time": "2026-03-01T...",
      "content_hash": "sha256...",
      "pinecone_chunk_ids": ["id1", "id2"],
      "last_ingested": "2026-03-05T...",
      "chunk_count": 12
    }
  }
}
```

## Comando
```bash
PYTHONPATH=. python tools/state/detect_changes.py
```

## Primeira Execução
Na primeira execução (sem state.json), TODOS os arquivos são classificados como `add`.
