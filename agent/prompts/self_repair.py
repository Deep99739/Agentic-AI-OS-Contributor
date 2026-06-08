"""
Layer 3 (Defense-in-Depth): Self-Repair Prompt.

When the best candidate scores < 10, this prompt feeds the build/test errors
back to the LLM so it can fix them without changing the core logic.

Improvements (Phase 2):
- Improvement 2: Receives PATCHED file contents (not originals)
- Improvement 3: Supports REGRESSION mode (expand fix) vs SYNTAX mode (fix errors only)
"""

SELF_REPAIR_PROMPT = """You are an expert Go developer. Your previous patch had build or test errors. Your task is to fix the errors.

## Repair Mode: {repair_mode}

{regression_guidance}

## Build/Test Errors
{error_output}

## Your Previous Patch (that caused the errors)
{previous_patch}

## Current Source Code (AFTER your patch was applied)
{file_contents}

## Test Conventions (MUST follow these exactly)
{test_conventions}

## Rules
1. If this is a SYNTAX repair: Fix ONLY the compilation errors, vet warnings, or syntax issues. Keep the core bug fix logic EXACTLY as-is.
2. If this is a REGRESSION repair: Your core fix approach is CORRECT but INCOMPLETE. EXPAND the fix to handle additional patterns that the existing tests expect. For example, if your regex fix is too narrow, widen it to also match the patterns shown in the failing tests.
3. Common fixes include:
   - Wrong import path or missing import
   - Wrong assertion function name (e.g., assert.Equal vs Equal for dot imports)
   - Missing type conversions or interface assertions
   - Syntax errors (missing brackets, wrong indentation)
   - Regex patterns that are too restrictive (need to add more character classes)
4. If the error is in test code, match the project's existing test conventions shown above.
5. Do NOT introduce new test dependencies.
6. Output corrected SEARCH/REPLACE blocks using the exact same format.

## SEARCH/REPLACE Format

path/to/file.go
```go
<<<<<<< SEARCH
exact existing code to find (from the ALREADY-PATCHED file)
=======
your corrected replacement code
>>>>>>> REPLACE
```

## Important
- The SEARCH text must match what is currently in the file AFTER your previous patch was applied.
- For REGRESSION repairs: look at the failing test input (e.g., "0 0 12 * * ?") and ensure your fix handles those patterns.
- Make the smallest possible change to fix the errors.
"""
