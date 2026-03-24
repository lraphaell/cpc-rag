# Workflow: RAG Ingestion Pipeline (Master)

## Objetivo
Orquestrar a ingestão incremental de documentos do dataset do time Genova para uma base vetorial Pinecone, detectando alterações semanais e evitando duplicatas.

## Inputs
- **Dataset**: Google Sheets `1gSMuR9YLn6ZfmUGJDODL0bz7jXwpQWqpT0xABa1i2Kc` (lista de arquivos com links)
- **Pinecone**: Index `agentic-rag`, namespace `genova-prod`
- **Auth**: gcloud CLI ou token.json (padrão Mandoo)

## Pipeline de Execução

```
Fetch Dataset → Detect Changes → Download → Data Cleanup → Metadata Extraction → Ingest → Report
     (script)      (script)      (script)     (script)          (AGENT)         (script)  (script)
```

### Stage 1: Fetch Dataset
- **Tool**: `tools/fetch/fetch_dataset.py`
- **Input**: Google Sheets ID
- **Output**: `.tmp/dataset.json` com lista estruturada de arquivos
- **Comando**: `PYTHONPATH=. python tools/fetch/fetch_dataset.py`
- **Nota**: Folders no dataset são expandidos (lista-se o conteúdo recursivamente)

### Stage 2: Detect Changes
- **Tool**: `tools/state/detect_changes.py`
- **Input**: `.tmp/dataset.json` + `.tmp/state.json`
- **Output**: `.tmp/change_manifest.json` com lista de {add, update, delete}
- **Comando**: `PYTHONPATH=. python tools/state/detect_changes.py`
- **Decisão pós-execução**:
  - Se nenhuma mudança → reportar "no updates needed" e parar
  - Se há mudanças → seguir para Stage 3

### Stage 3: Download Files
- **Tool**: `tools/fetch/download_files.py`
- **Input**: `.tmp/change_manifest.json` (baixa só os add + update)
- **Output**: Arquivos em `.tmp/downloads/` + `.tmp/download_manifest.json`
- **Comando**: `PYTHONPATH=. python tools/fetch/download_files.py`

### Stage 4: Data Cleanup (Parse + Chunk)
- **Tool**: `tools/cleanup/prepare_chunks.py`
- **Input**: Arquivos em `.tmp/downloads/` + `.tmp/change_manifest.json`
- **Output**: JSONs intermediários em `.tmp/cleaned/{drive_id}.json`
- **Comando**: `PYTHONPATH=. python tools/cleanup/prepare_chunks.py`
- **O que faz**:
  - Parseia cada arquivo (pdf, docx, xlsx, pptx, csv, txt)
  - **Para planilhas com dados tabulares (>12% dígitos)**: gera resumos analíticos (`summary_analytical`) em vez de chunks brutos — descreve colunas, estatísticas, valores categóricos e sample de dados
  - Para texto narrativo: chunka usando semantic chunker (fallback: fixed)
  - Gera JSON intermediário com chunks e metadata fields **vazios**
  - Marca `metadata_status: "pending_agent_review"`

### Stage 5: Metadata Extraction (AGENT)
- **Quem executa**: O agente (Claude Code no VSCode)
- **Workflow**: `workflows/metadata_extraction.md`
- **Input**: JSONs em `.tmp/cleaned/` com `metadata_status: "pending_agent_review"`
- **Output**: Mesmos JSONs com metadata preenchida per-chunk e `metadata_status: "reviewed"`
- **O que faz**: Para cada chunk, o agente analisa o texto e extrai:
  - `team` (Genova, Relacionamiento con las banderas, Negocio cross, Bari, Mejora Continua y Planning, Scheme enablers, Optimus, X Countries)
  - `country` (MLA, MLB, MLM, MLU, MLC, MCO, Corp)
  - `bandera` (Visa, Mastercard, American Express, Cabal, Elo, Hipercard, Carnet, Naranja, Otra)
  - `fecha` (2025-Q1, 2026-Q2, etc. formato YYYY-QN)
- **Nota**: Esta é a etapa probabilística — o agente decide a metadata baseado no conteúdo

### Stage 6: Ingest to Pinecone
- **Tool**: `tools/ingestion/process_and_ingest.py`
- **Input**: JSONs reviewed em `.tmp/cleaned/` + `.tmp/change_manifest.json`
- **Output**: `.tmp/ingestion_log.json` + chunks no Pinecone
- **Comando**: `PYTHONPATH=. python tools/ingestion/process_and_ingest.py`
- **Comportamento incremental**:
  - Para arquivos "update": deleta chunks antigos por `drive_file_id` antes de re-ingerir
  - Para arquivos "delete": só deleta chunks do Pinecone
  - Para arquivos "add": ingestão completa
  - Só ingere arquivos com `metadata_status: "reviewed"`
  - State é atualizado per-file após sucesso

### Stage 7: Report
- **Tool**: `tools/reporting/generate_report.py`
- **Input**: `.tmp/ingestion_log.json`
- **Output**: Google Sheets URL
- **Comando**: `PYTHONPATH=. python tools/reporting/generate_report.py`

## Execução Rápida (End-to-End)

```bash
# 1. Verificar auth
CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.13 gcloud auth print-access-token > /dev/null && echo "OK"

# 2. Pipeline (stages determinísticos)
cd "/Users/lraphael/Documents/Agents - IA - Cloude - Scripts/Data Cleanup for RAG Agent"
PYTHONPATH=. python tools/fetch/fetch_dataset.py
PYTHONPATH=. python tools/state/detect_changes.py
PYTHONPATH=. python tools/fetch/download_files.py
PYTHONPATH=. python tools/cleanup/prepare_chunks.py

# 3. Stage 5: AGENT extrai metadata per-chunk (ver workflows/metadata_extraction.md)
#    O agente lê cada JSON em .tmp/cleaned/, analisa os chunks, preenche metadata

# 4. Ingestão + Report
PYTHONPATH=. python tools/ingestion/process_and_ingest.py
PYTHONPATH=. python tools/reporting/generate_report.py
```

## Tratamento de Erros

| Cenário | Ação |
|---------|------|
| Auth falhou | Executar `gcloud auth login --enable-gdrive-access` |
| Sheets inacessível | Verificar ID e permissões |
| Arquivo não baixou | Logar erro, continuar com os demais |
| Parser falhou | Tentar parser fallback, logar e continuar |
| Metadata extraction incompleta | Agente pode re-processar chunks específicos |
| Pinecone rate limit | Retry com backoff (automático no pinecone_client) |
| state.json corrompido | Deletar e rodar pipeline completo |

## Dados Intermediários

```
.tmp/
  dataset.json           # Stage 1: lista de arquivos do Sheets
  change_manifest.json   # Stage 2: add/update/delete detectados
  download_manifest.json # Stage 3: resultados do download
  downloads/             # Stage 3: arquivos baixados
  cleanup_manifest.json  # Stage 4: resultados do parse+chunk
  cleaned/               # Stage 4→5: JSONs intermediários (chunks + metadata)
    {drive_id}.json      #   - metadata_status: "pending_agent_review" → "reviewed"
  ingestion_log.json     # Stage 6: resultados da ingestão
  state.json             # Persistente: tracking de versões (NÃO deletar)
```

## Notas
- O `state.json` é o único arquivo em `.tmp/` que NÃO deve ser deletado entre runs
- Os JSONs em `.tmp/cleaned/` servem como checkpoint — podem ser re-ingeridos sem re-processar
- Primeira execução: todos os arquivos serão "add" (sem state prévio)
- Execuções subsequentes: apenas alterações detectadas
- Arquivos removidos do Sheets são automaticamente limpos do Pinecone
