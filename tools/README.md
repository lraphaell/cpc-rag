# Tools Directory

This directory contains Python scripts that do the actual execution work.

## What Goes Here

Deterministic, testable scripts that:
- Make API calls
- Transform data
- Interact with files and databases
- Scrape websites
- Generate outputs

## Guidelines

**1. Single Responsibility**
Each tool should do one thing well. If a script is doing too much, split it into multiple tools.

**2. Clear Interfaces**
- Use command-line arguments for inputs
- Print clear status messages
- Return proper exit codes (0 for success, non-zero for errors)
- Output structured data (JSON, CSV, etc.)

**3. Error Handling**
- Validate inputs before processing
- Catch and report errors clearly
- Don't silently fail

**4. Configuration**
- Use environment variables from `.env` for secrets
- Use command-line args for runtime parameters
- Document all required configuration

## Example Tool Structure

```python
#!/usr/bin/env python3
"""
Tool Name: Brief description

Usage:
    python tool_name.py --arg1 value1 --arg2 value2

Required Environment Variables:
    API_KEY: Description of what this key is for
"""

import os
import sys
import argparse
from dotenv import load_dotenv

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="Tool description")
    parser.add_argument("--arg1", required=True, help="Argument description")
    args = parser.parse_args()

    # Your logic here

    print("Success message")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

## Testing

Before considering a tool "done":
1. Test with valid inputs
2. Test with invalid inputs
3. Test error conditions
4. Verify it works with the workflow

## Documentation

Each tool should have:
- Docstring explaining what it does
- Usage examples
- Required environment variables
- Expected inputs and outputs
