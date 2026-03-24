# Workflow: Validação Completa e Re-ingestão

## Contexto
Após o primeiro pipeline run, ficaram chunks órfãos no Pinecone (dados transacionais raw ingeridos antes de serem substituídos por resumos analíticos). Este workflow faz uma limpeza completa e re-ingestão validada.

## Quando executar
- Após o primeiro pipeline run (para limpar órfãos)
- Quando houver suspeita de inconsistência entre state.json e Pinecone
- Para reconstruir o namespace do zero

## Pré-requisitos
- `.tmp/cleaned/*.json` com `metadata_status: "reviewed"` — estes são a source of truth
- gcloud auth ativo
- Pinecone acessível

## Execução

### Step 1: Limpar namespace genova-prod
```bash
cd "/Users/lraphael/Documents/Agents - IA - Cloude - Scripts/Data Cleanup for RAG Agent"
PYTHONPATH=. python3 -c "
from tools.ingestion.pinecone_client import PineconeClient
import time
client = PineconeClient()
print('Clearing genova-prod...')
client.index.delete(delete_all=True, namespace='genova-prod')
time.sleep(10)
stats = client.index.describe_index_stats()
gp = stats.namespaces.get('genova-prod')
print(f'After clear: {gp.vector_count if gp else 0} vectors')
"
```

### Step 2: Inventariar cleaned JSONs
```bash
PYTHONPATH=. python3 -c "
import json, glob
total_files = 0
total_chunks = 0
for f in glob.glob('.tmp/cleaned/*.json'):
    with open(f) as fh:
        data = json.load(fh)
    if data.get('metadata_status') == 'reviewed':
        total_files += 1
        total_chunks += len(data.get('chunks', []))
print(f'Files to ingest: {total_files}')
print(f'Expected chunks: {total_chunks}')
"
```
**Esperado**: 134 files, ~1196 chunks

### Step 3: Re-ingerir tudo
```bash
PYTHONPATH=. python3 tools/ingestion/process_and_ingest.py
```
Este comando lê todos os cleaned JSONs com `metadata_status: "reviewed"` e ingere no Pinecone.

**Nota sobre rate limit**: O free tier do Pinecone limita requests. Se der 429, o script tem retry automático com backoff exponencial. Pode levar ~15-20 min para ~1200 chunks.

Se o script padrão der problemas de rate limit, usar o script com delay maior:
```bash
PYTHONPATH=. python3 << 'EOF'
import json, glob, time
from tools.ingestion.pinecone_client import PineconeClient, flatten_metadata
from tools.state.update_state import save_state
from tools.common.config import TMP_DIR
from datetime import datetime, timezone

CLEANED_DIR = TMP_DIR / "cleaned"
client = PineconeClient()
ns = "genova-prod"
new_state = {"last_run": datetime.now(timezone.utc).isoformat(), "files": {}}
count = 0
total_chunks = 0

for fpath in sorted(CLEANED_DIR.glob("*.json")):
    with open(fpath) as f:
        data = json.load(f)
    if data.get("metadata_status") != "reviewed":
        continue

    rid = data.get("drive_id", "")
    name = data.get("file_name", "")
    chunks = data.get("chunks", [])

    records = []
    chunk_ids = []
    for chunk in chunks:
        idx = chunk.get("chunk_index", 0)
        cid = f"{rid}_{idx:04d}"
        chunk_ids.append(cid)
        meta = {
            "drive_file_id": rid, "file_name": name,
            "file_type": data.get("file_type", ""),
            "chunk_index": idx, "total_chunks": len(chunks),
            "source_url": data.get("source_url", ""),
            "modified_time": data.get("modified_time", ""),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "chunking_method": data.get("chunking_method", ""),
        }
        for k, v in chunk.get("metadata", {}).items():
            if v is not None and v != "":
                meta[k] = v
        flat = flatten_metadata(meta)
        record = {"id": cid, "text": chunk["text"]}
        record.update(flat)
        records.append(record)

    try:
        upserted = client.upsert_records(records, namespace=ns, batch_size=50, delay_between_batches=10)
        count += 1
        total_chunks += upserted
        new_state["files"][rid] = {
            "name": name, "drive_id": rid,
            "modified_time": data.get("modified_time", ""),
            "pinecone_chunk_ids": chunk_ids,
            "last_ingested": datetime.now(timezone.utc).isoformat(),
            "chunk_count": len(chunk_ids),
        }
        print(f"[{count}] OK: {name[:50]} ({upserted} chunks)")
    except Exception as e:
        print(f"[{count+1}] ERROR: {name[:50]} - {e}")

    if count % 5 == 0:
        time.sleep(5)

save_state(new_state)
print(f"\nDone: {count} files, {total_chunks} chunks")
EOF
```

### Step 4: Validar
```bash
PYTHONPATH=. python3 -c "
import json
from tools.ingestion.pinecone_client import PineconeClient
from tools.common.config import TMP_DIR

# Pinecone
client = PineconeClient()
stats = client.index.describe_index_stats()
gp = stats.namespaces.get('genova-prod')
pinecone_count = gp.vector_count if gp else 0

# State
with open(TMP_DIR / 'state.json') as f:
    state = json.load(f)
state_files = len(state['files'])
state_chunks = sum(f['chunk_count'] for f in state['files'].values())

# Cleaned JSONs
import glob
cleaned_chunks = 0
cleaned_files = 0
for f in glob.glob(str(TMP_DIR / 'cleaned' / '*.json')):
    with open(f) as fh:
        data = json.load(fh)
    if data.get('metadata_status') == 'reviewed':
        cleaned_files += 1
        cleaned_chunks += len(data.get('chunks', []))

print(f'Cleaned JSONs:   {cleaned_files} files, {cleaned_chunks} chunks')
print(f'State.json:      {state_files} files, {state_chunks} chunks')
print(f'Pinecone:        {pinecone_count} vectors')
print()
if cleaned_chunks == state_chunks == pinecone_count:
    print('VALIDATION: PASS - all 3 sources match')
elif state_chunks == pinecone_count:
    print('VALIDATION: PARTIAL - state matches Pinecone but not cleaned JSONs')
else:
    print(f'VALIDATION: MISMATCH')
    print(f'  cleaned - state = {cleaned_chunks - state_chunks}')
    print(f'  cleaned - pinecone = {cleaned_chunks - pinecone_count}')
"
```

### Step 5: Test query
```bash
PYTHONPATH=. python3 -c "
from tools.ingestion.pinecone_client import PineconeClient
client = PineconeClient()
results = client.query('topics MLB 2026', top_k=3, namespace='genova-prod')
for r in results:
    print(f'  {r.get(\"score\",0):.4f} | {r.get(\"file_name\",\"\")[:50]} | country={r.get(\"country\",\"?\")}')
"
```

## Checklist de Validação
- [ ] Pinecone genova-prod vectors = cleaned JSONs chunks = state.json chunks
- [ ] Query sem filtro retorna resultados relevantes
- [ ] Query com filtro country=MLB retorna resultados de Brasil
- [ ] Query com filtro bandera=Visa retorna resultados de Visa
- [ ] state.json tem todos os 134 files
- [ ] Nenhum chunk órfão no Pinecone

## Estado atual (2026-03-12)
- **Namespace foi limpo mas re-ingestão foi interrompida**
- Precisa rodar Steps 3-5 para completar
- Cleaned JSONs estão intactos em `.tmp/cleaned/` (134 files, ~1196 chunks)
- 23 files não baixados (exportSizeLimitExceeded) — lista em `.tmp/failed_downloads.json`
