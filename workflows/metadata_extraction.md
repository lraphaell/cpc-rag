# Workflow: Metadata Extraction (Agent-Driven)

## Objetivo
Analisar cada chunk dos JSONs intermediários em `.tmp/cleaned/` e preencher os campos de metadata filtráveis (`team`, `country`, `bandera`, `fecha`) baseado no conteúdo do texto.

## Quem executa
O **agente** (Claude Code no VSCode) — NÃO um script. A extração requer compreensão semântica do conteúdo.

## Input
- JSONs em `.tmp/cleaned/{drive_id}.json` com `metadata_status: "pending_agent_review"`
- Cada JSON contém chunks com metadata fields vazios

## Output
- Mesmos JSONs atualizados com metadata preenchida e `metadata_status: "reviewed"`

---

## Valores Válidos (Referência Oficial)

### Country
| Código | País |
|--------|------|
| `MLA` | Argentina |
| `MLB` | Brasil |
| `MLM` | México |
| `MLU` | Uruguay |
| `MLC` | Chile |
| `MCO` | Colombia |
| `Corp` | Global / Otros / Cross-country |

### Team
| Valor |
|-------|
| `Genova` |
| `Relacionamiento con las banderas` |
| `Negocio cross` |
| `Bari` |
| `Mejora Continua y Planning` |
| `Scheme enablers` |
| `Optimus` |
| `X Countries` |

### Bandera
| Valor |
|-------|
| `Visa` |
| `Mastercard` |
| `American Express` |
| `Cabal` |
| `Elo` |
| `Hipercard` |
| `Carnet` |
| `Naranja` |
| `Otra` |

### Fecha
- Formato: `YYYY-QN` (ejemplo: `2025-Q1`, `2026-Q3`)
- Mapeo de meses a quarters:
  - Enero-Marzo → Q1
  - Abril-Junio → Q2
  - Julio-Septiembre → Q3
  - Octubre-Diciembre → Q4
- Si pide "2025" → `["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]`

---

## Campos a extrair por chunk

| Campo | Tipo | Default (cuando no se detecta) | Regla |
|-------|------|-------------------------------|-------|
| `team` | string o list | `"Genova"` | Team responsable del contenido. Si no es claro, default Genova |
| `country` | string o list | `"Corp"` | País(es) mencionado(s). Si es global o no especifica, usar `"Corp"` |
| `bandera` | string o list | `"Otra"` | Bandera(s) mencionada(s). Si no especifica, usar `"Otra"` |
| `fecha` | string o list | `""` | Período temporal. Formato `YYYY-QN`. Vacío si no hay referencia temporal |

**Regla del operador `$in`**: Cuando un campo tiene múltiples valores, siempre usar lista.
Ejemplo: Un chunk que menciona MLA y MLB → `country: ["MLA", "MLB"]`

---

## Procedimiento para el Agente

### Paso 1: Listar archivos pendientes
```python
import json, glob
pending = []
for f in glob.glob(".tmp/cleaned/*.json"):
    with open(f) as fh:
        data = json.load(fh)
    if data.get("metadata_status") == "pending_agent_review":
        pending.append(f)
print(f"{len(pending)} files pending review")
```

### Paso 2: Para cada archivo, leer los chunks y analizar
Para cada chunk:
1. Leer el `text`
2. Identificar menciones a países → mapear a código (Argentina→MLA, Brasil→MLB, etc.)
3. Identificar menciones a banderas → usar nombre oficial (Mastercard, no MC)
4. Identificar período temporal → convertir a `YYYY-QN`
5. Identificar team → usar nombre oficial de la lista
6. Rellenar los campos de metadata

### Paso 3: Guardar el JSON actualizado
```python
data["metadata_status"] = "reviewed"
with open(file_path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

---

## Reglas de Extracción

### Country
- Buscar siglas directas: MLB, MLA, MLM, MLC, MCO, MLU
- Buscar nombres de países: "Brasil"→MLB, "Argentina"→MLA, "México"→MLM, "Chile"→MLC, "Colombia"→MCO, "Uruguay"→MLU
- Si el chunk es consolidado (varios países o global) → `"Corp"`
- Si no hay mención a país → `"Corp"`
- Múltiples países → lista: `["MLA", "MLB"]`

### Bandera
- Buscar nombres: Visa, Mastercard (no MC), American Express (no Amex), Elo, Cabal, Hipercard, Carnet, Naranja
- Alias conocidos: "MC" → "Mastercard", "Amex" → "American Express", "PROSA" → tratarlo como contexto de MLM no como bandera
- Múltiples banderas → lista: `["Visa", "Mastercard"]`
- Si no hay mención → `"Otra"`

### Fecha
- Buscar referencias temporales: "Q1 2025", "noviembre 2025", "enero 2026", "H1 2025"
- Convertir meses: "noviembre 2025" → "2025-Q4", "marzo 2026" → "2026-Q1"
- Convertir semestres: "H1 2025" → ["2025-Q1", "2025-Q2"], "H2 2025" → ["2025-Q3", "2025-Q4"]
- Si el chunk referencia un año completo: "2025" → ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"]
- Si hay rango (e.g., "2025-2026") → usar el más reciente
- Si no hay referencia temporal → `""`

### Team
- Default: `"Genova"` (la mayoría del dataset es del equipo Genova)
- Buscar menciones explícitas: "Bari", "Optimus", "Scheme enablers", "Mejora Continua", etc.
- Si el contenido es sobre relación con banderas → `"Relacionamiento con las banderas"`
- Si es negocio entre países → `"Negocio cross"` o `"X Countries"`

---

## Validación
Después de la extracción, verificar:
- [ ] Todos los valores de `country` están en la lista válida (MLA, MLB, MLM, MLU, MLC, MCO, Corp)
- [ ] Todos los valores de `bandera` están en la lista válida
- [ ] Todos los valores de `team` están en la lista válida
- [ ] `fecha` en formato `YYYY-QN` cuando está rellenado
- [ ] `metadata_status` actualizado a `"reviewed"` en todos los archivos
- [ ] No hay chunks con country, bandera Y fecha todos vacíos (a menos que sea contenido genérico como índice o footer)

## Notas
- Precisión > cobertura: metadata ausente es mejor que metadata incorrecta
- Para chunks genéricos (tabla de contenido, footer, encabezados) es OK dejar campos con defaults
- El agente puede procesar múltiples archivos en paralelo usando sub-agentes si es necesario
- PROSA no es una bandera — es el procesador de pagos en México. Si aparece, el country es MLM
