REPAIR_PROMPT = """You are an expert Go developer tasked with fixing a GitHub issue. Generate precise code edits using the SEARCH/REPLACE format.

## GitHub Issue
**Title**: {issue_title}
**Description**:
{issue_body}

## Analysis of What Needs to Change
{element_analysis}

## Repository Context
{repo_map_snippet}

## Current Source Code
{file_contents}

## Rules for Code Edits
1. You MUST use the exact SEARCH/REPLACE format shown below.
2. The SEARCH block must contain EXACT text from the current source code. Copy it verbatim.
3. The REPLACE block contains your modified version of that code.
4. Keep changes minimal and surgical. Don't rewrite entire functions unless necessary.
5. Follow existing code style and conventions exactly.
6. Handle errors using Go idioms (if err != nil).
7. Run gofmt-compatible formatting.
8. Add comments only where the existing code has comments in similar places.
9. Ensure all imports are correct. Add new imports if needed.

## SEARCH/REPLACE Format

For each file you need to edit, output the file path on its own line, then a code block:

path/to/file.go
```go
<<<<<<< SEARCH
exact existing code to find
=======
your replacement code
>>>>>>> REPLACE
```

If you need to make multiple edits to the same file, output multiple SEARCH/REPLACE blocks under the same file path.

If you need to edit multiple files, repeat the pattern for each file.

## Important
- The SEARCH text must EXACTLY match the current source code, including whitespace and indentation.
- Make the smallest possible change that fixes the issue correctly.
- If the fix requires adding new functions, show them in a SEARCH/REPLACE where the SEARCH is the area just before where the new code should go.
"""
