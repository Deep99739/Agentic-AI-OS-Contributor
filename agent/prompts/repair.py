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
(Line numbers are shown for reference only — do NOT include them in SEARCH blocks)
{file_contents}

## Test Conventions (MUST follow these exactly when writing test code)
{test_conventions}

## Existing Test Cases (your fix MUST pass ALL of these)
CRITICAL: Before writing your fix, carefully analyze the test inputs below. Your changes must handle
ALL patterns shown in these tests. For regex changes: verify every test input matches your new regex.
For example, if test inputs contain characters like ?, L, #, or letters — your regex MUST support them.
{relevant_test_cases}

## Rules for Code Edits
1. You MUST use the exact SEARCH/REPLACE format shown below.
2. The SEARCH block must contain EXACT text from the current source code. Copy it VERBATIM.
3. Do NOT include line numbers in the SEARCH or REPLACE blocks — they are for reference only.
4. The REPLACE block contains your modified version of that code.
5. Keep changes minimal and surgical. Don't rewrite entire functions unless necessary.
6. Follow existing code style and conventions exactly.
7. Handle errors using Go idioms (if err != nil).
8. Run gofmt-compatible formatting.
9. Add comments only where the existing code has comments in similar places.
10. Ensure all imports are correct. Add new imports if needed.
11. Use tabs for indentation (Go standard).
12. If you modify or add test code, you MUST match the test conventions above exactly. Do NOT introduce new test dependencies or assertion libraries.

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
- The SEARCH text must EXACTLY match the current source code, including whitespace, tabs, and indentation.
- Copy the code character-by-character. Even a single space difference will cause the patch to fail.
- Make the smallest possible change that fixes the issue correctly.
- If the fix requires adding new functions, show them in a SEARCH/REPLACE where the SEARCH is the area just before where the new code should go.
- CRITICAL: Your fix MUST pass ALL existing tests in the repository. If the existing test suite expects certain inputs to be valid, your fix must preserve that behavior. Do not break backward compatibility.
- REGEX FIX CHECKLIST: If your fix modifies a regex, you MUST mentally verify EACH test case input against your new regex pattern before producing the final patch. Walk through character by character. If a test input like "0 0 12 * * ?" contains a character your regex doesn't support (like ?), you MUST expand the regex character classes to support it.
"""
