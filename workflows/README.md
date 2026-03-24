# Workflows Directory

This directory contains workflow definitions - your SOPs (Standard Operating Procedures) written in Markdown.

## What Goes Here

Each workflow file should define:
- **Objective**: What are we trying to accomplish?
- **Inputs**: What information/data is required to start?
- **Tools**: Which tools from `tools/` should be used?
- **Process**: Step-by-step instructions
- **Outputs**: What gets produced and where it goes
- **Edge Cases**: Known issues, rate limits, error handling

## Example Structure

```markdown
# Workflow Name

## Objective
Clear description of what this workflow accomplishes

## Required Inputs
- Input 1: Description
- Input 2: Description

## Tools Used
- `tools/script1.py` - What it does
- `tools/script2.py` - What it does

## Process
1. First step
2. Second step
3. Third step

## Expected Outputs
- Output 1: Where it goes
- Output 2: Where it goes

## Edge Cases & Notes
- Rate limits: X requests per minute
- Known issue: Y happens when Z
- Workaround: Do this instead
```

## Living Documents

Workflows should evolve as you learn. When you discover better approaches, encounter constraints, or solve recurring issues, update the workflow so the knowledge persists.
