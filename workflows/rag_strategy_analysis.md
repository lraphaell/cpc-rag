# RAG Strategy Analysis Workflow

## Objective
Use the `rag-strategy-analyzer` agent to analyze each document and recommend optimal RAG ingestion strategies tailored to file type, structure, and content characteristics.

## Overview

This workflow coordinates between the main Claude agent and the specialized `rag-strategy-analyzer` agent to produce a comprehensive strategy analysis for all documents in the collection.

**Key Principle**: Different document types require different processing strategies. A one-size-fits-all approach sacrifices retrieval accuracy.

## Agent Role: rag-strategy-analyzer

The `rag-strategy-analyzer` is a specialized agent (defined in `.claude/agents/rag-strategy-analyzer.md`) with expertise in:
- Document structure analysis
- RAG pipeline design
- Chunking strategy selection
- Metadata extraction planning
- Data cleanup requirements

**Agent Model**: Sonnet 4.5 (balanced speed and capability)

## Input Requirements

The agent requires for each file:
1. **File path**: Local path to the downloaded file
2. **File name**: Original filename with extension
3. **File type**: Format classification (PDF, DOCX, XLSX, etc.)
4. **Basic metadata** (optional): Size, modification date

**Input Source**: `file_manifest.json` from Google Drive fetch stage

## Expected Output Structure

The agent returns a **10-column analysis** for each file:

| Column # | Name | Description | Example |
|----------|------|-------------|---------|
| 1 | File ID | Unique identifier | `file_001` |
| 2 | File Name | Original filename | `quarterly_report.pdf` |
| 3 | File Type | Format classification | `PDF` |
| 4 | Detected Structure | Structural type with justification | `Semi-Structured: Document with headings, tables, and narrative sections` |
| 5 | Recommended RAG Strategy | High-level approach | `Section-based chunking with table preservation` |
| 6 | Chunking Method | Specific strategy with parameters | `Semantic chunking, 500-token target, 50-token overlap, preserve table boundaries` |
| 7 | Metadata Strategy | What metadata to extract | `Extract: section headers, page numbers, table names, document date` |
| 8 | Retrieval Type | Recommended approach | `Hybrid: Dense vector + BM25 keyword search for tables` |
| 9 | Required Data Cleanup | Preprocessing steps | `1. OCR quality check 2. Normalize whitespace 3. Extract tables separately` |
| 10 | Notes | Additional considerations | `Contains scanned pages - OCR quality varies. Preserve table structure for accurate retrieval.` |

## Orchestration Logic

This logic is executed by the **main Claude agent** (not a Python tool):

### Step 1: Load File Manifest
```python
import json

with open('.tmp/pipeline_run_{timestamp}/downloads/file_manifest.json') as f:
    manifest = json.load(f)

files_to_analyze = manifest['files']
```

### Step 2: Invoke Agent for Each File
```python
from tools.task import Task

strategies = []

for file_info in files_to_analyze:
    # Invoke rag-strategy-analyzer agent
    analysis = Task.invoke(
        subagent_type="rag-strategy-analyzer",
        description=f"Analyze {file_info['name']} for RAG strategy",
        prompt=f"""
        Analyze this file for RAG ingestion:

        File: {file_info['name']}
        Type: {file_info['mime_type']}
        Path: {file_info['local_path']}
        Size: {file_info['size_bytes']} bytes

        Provide complete 10-column analysis following the rag-strategy-analyzer format.
        """
    )

    strategies.append(analysis)
```

### Step 3: Aggregate Results
```python
import pandas as pd

# Convert agent responses to DataFrame
df = pd.DataFrame(strategies)

# Save to Excel with formatting
output_path = '.tmp/pipeline_run_{timestamp}/strategy_analysis.xlsx'
df.to_excel(output_path, index=False, sheet_name='RAG Strategies')
```

## Fallback Strategies

If agent invocation fails for a file, use these fallback strategies based on file type:

### PDF
- **Chunking**: Semantic chunking, 512 tokens, 50 overlap
- **Metadata**: Page numbers, document title
- **Retrieval**: Dense vector search
- **Cleanup**: Check for scanned pages, attempt OCR if needed

### DOCX (Word)
- **Chunking**: Section-based (by headings) or semantic
- **Metadata**: Section headers, document properties
- **Retrieval**: Dense vector search
- **Cleanup**: Normalize whitespace, remove formatting artifacts

### PPTX (PowerPoint)
- **Chunking**: Slide-level
- **Metadata**: Slide titles, presentation title, slide numbers
- **Retrieval**: Dense vector search
- **Cleanup**: Extract speaker notes, combine with slide content

### XLSX/CSV (Spreadsheets)
- **Chunking**: Row-based with column context
- **Metadata**: Sheet names, column headers, data types
- **Retrieval**: Hybrid (vector + structured queries)
- **Cleanup**: Handle nulls, standardize data types, deduplicate rows

### TXT (Plain Text)
- **Chunking**: Fixed-size, 512 tokens, 50 overlap
- **Metadata**: File name, encoding
- **Retrieval**: Dense vector search
- **Cleanup**: Detect encoding, normalize line endings

## Example: Complete Workflow

### Input
`file_manifest.json`:
```json
{
  "total_files": 3,
  "files": [
    {"id": "001", "name": "report.pdf", "mime_type": "application/pdf", "local_path": ".tmp/downloads/report.pdf"},
    {"id": "002", "name": "data.xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "local_path": ".tmp/downloads/data.xlsx"},
    {"id": "003", "name": "slides.pptx", "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "local_path": ".tmp/downloads/slides.pptx"}
  ]
}
```

### Processing
Main agent invokes `rag-strategy-analyzer` three times (once per file).

### Output
`strategy_analysis.xlsx`:

| File ID | File Name | File Type | Detected Structure | Recommended RAG Strategy | Chunking Method | Metadata Strategy | Retrieval Type | Required Data Cleanup | Notes |
|---------|-----------|-----------|-------------------|------------------------|----------------|-------------------|---------------|---------------------|-------|
| 001 | report.pdf | PDF | Semi-Structured | Section-based with table preservation | Semantic, 500 tokens, 50 overlap | Section headers, page #s, tables | Hybrid | OCR check, normalize whitespace | Mix of text and tables |
| 002 | data.xlsx | Excel | Structured | Row-level with column context | Row-based, include headers | Sheet names, columns, types | Structured + Vector | Handle nulls, dedupe | 3 sheets, financial data |
| 003 | slides.pptx | PowerPoint | Semi-Structured | Slide-level chunking | Slide-by-slide with notes | Slide titles, presentation title | Dense Vector | Extract notes, combine | 15 slides with speaker notes |

## Integration with Next Stage

The `strategy_analysis.xlsx` file becomes the **primary input** for the RAG Ingestion Execution stage.

Each row in the Excel file tells the ingestion tool:
1. Which file to process
2. Which parser to use
3. How to chunk the content
4. What metadata to extract
5. What cleanup steps to apply

**Data Flow:**
```
file_manifest.json → rag-strategy-analyzer (per file) → strategy_analysis.xlsx → execute_rag_ingestion.py
```

## Performance Considerations

**For small collections (< 100 files):**
- Sequential agent invocations are fine
- Average: ~10-15 seconds per file analysis
- Total time for 20 files: ~3-5 minutes

**Agent invocation is the bottleneck**, not file I/O:
- Agent needs to read file, analyze structure, generate recommendations
- Complex files (large PDFs, multi-sheet Excel) take longer

**Optimization**: Could parallelize agent invocations (max 3 concurrent) for larger collections, but unnecessary for small scale.

## Error Handling

### File Read Errors
**Problem**: Agent cannot read file (corrupted, permissions issue)
**Solution**:
1. Log error with file details
2. Mark file as "unprocessable" in strategy analysis
3. Use fallback strategy: skip or manual review flag
4. Continue with remaining files

### Agent Timeout
**Problem**: Agent takes too long (>60 seconds)
**Solution**:
1. Cancel agent invocation
2. Log timeout with file details
3. Apply fallback strategy for file type
4. Continue with remaining files

### Invalid Agent Response
**Problem**: Agent returns incomplete or malformed analysis
**Solution**:
1. Validate response has all 10 columns
2. If missing data, use fallback strategy to fill gaps
3. Log warning but continue processing

### Complete Agent Failure
**Problem**: Agent system is down or unavailable
**Solution**:
1. Fall back to type-based strategy table (see Fallback Strategies above)
2. Log that automated analysis was skipped
3. Generate strategy_analysis.xlsx using fallback logic
4. Mark in notes: "Fallback strategy - manual review recommended"

## Quality Validation

After generating `strategy_analysis.xlsx`, validate:

1. **Row count matches file count**: Each file has exactly one strategy
2. **All required columns present**: 10 columns with correct headers
3. **No empty critical fields**: File ID, File Name, Chunking Method must be populated
4. **Chunking parameters are valid**: Token sizes are reasonable (100-2000), overlap < chunk size

**Validation Script** (can be added to workflow):
```python
import pandas as pd

df = pd.read_excel('strategy_analysis.xlsx')

assert len(df) == len(files_to_analyze), "Row count mismatch"
assert list(df.columns) == EXPECTED_COLUMNS, "Column mismatch"
assert df['File ID'].notna().all(), "Missing File IDs"
assert df['Chunking Method'].notna().all(), "Missing chunking methods"

print("✓ Strategy analysis validated successfully")
```

## Troubleshooting

### "Agent returned unexpected format"
- Check agent definition hasn't been modified
- Verify agent is using correct model (Sonnet 4.5)
- Try re-invoking agent with clearer prompt

### "Analysis seems incorrect for file type"
- Verify file was downloaded correctly (not corrupted)
- Check file extension matches actual content
- Consider manual review for critical files

### "Chunking parameters are too large/small"
- Agent recommendations are guidelines, not strict rules
- Can override in ingestion stage if needed
- Adjust based on actual retrieval performance

## Next Workflow

After completing strategy analysis:
→ [RAG Ingestion Execution](rag_ingestion_execution.md)

This workflow will read `strategy_analysis.xlsx` and execute the recommended strategies for each file.
