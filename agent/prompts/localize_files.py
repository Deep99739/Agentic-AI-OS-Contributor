FILE_LOCALIZATION_PROMPT = """You are an expert Go developer analyzing a GitHub issue to identify which source files need to be modified.

## GitHub Issue
**Title**: {issue_title}
**Description**:
{issue_body}

## Repository Structure (Go files)
{repo_map}

## Keyword Search Results
{grep_hints}

## Your Task
Analyze the issue and identify the **top 5 most relevant Go source files** that would need to be modified to fix this issue. 

Rules:
1. Focus on SOURCE files (not test files) unless the issue is specifically about tests.
2. Include test files ONLY if they need new test cases for the fix.
3. List files by relevance (most important first).
4. Use the exact file paths as shown in the repository structure.
5. Do NOT include vendor/ or third-party files.

## Output Format
List exactly the file paths, one per line, nothing else:

path/to/file1.go
path/to/file2.go
path/to/file3.go
path/to/file4.go
path/to/file5.go
"""
