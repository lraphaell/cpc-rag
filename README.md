# WAT Framework Project

**Workflows, Agents, Tools** - A reliable architecture for AI-driven automation

## What This Is

This project uses the WAT framework to separate concerns:
- **Workflows** (`workflows/`) - Plain language instructions defining what to do
- **Agents** (Claude) - Intelligent coordination and decision-making
- **Tools** (`tools/`) - Python scripts that execute deterministic tasks

## Quick Start

1. **Set up Python environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure API keys**
   - Edit `.env` and add your API keys
   - Never commit `.env` to version control

3. **Add Google OAuth (if needed)**
   - Download `credentials.json` from Google Cloud Console
   - Place it in the root directory (already gitignored)
   - First run will generate `token.json` automatically

## Directory Structure

```
workflows/      # Markdown SOPs (what to do and how)
tools/          # Python scripts (deterministic execution)
.tmp/           # Temporary/intermediate files (regenerated as needed)
.env            # API keys and secrets (gitignored)
```

## How to Use

1. Define your workflow in `workflows/your_workflow.md`
2. Build necessary tools in `tools/your_tool.py`
3. Run through Claude, who orchestrates the process
4. Iterate and improve based on what you learn

## Core Principle

**Local files are for processing. Final deliverables go to cloud services.**

Everything in `.tmp/` is disposable. Final outputs should be in Google Sheets, Slides, or other accessible cloud platforms.

## See Also

Read [CLAUDE.md](CLAUDE.md) for complete agent instructions and operational guidelines.
