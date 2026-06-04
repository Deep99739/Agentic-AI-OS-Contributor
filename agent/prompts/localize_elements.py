ELEMENT_LOCALIZATION_PROMPT = """You are an expert Go developer. Given a GitHub issue and the source code of relevant files, identify the EXACT functions, methods, or struct definitions that need to be modified.

## GitHub Issue
**Title**: {issue_title}
**Description**:
{issue_body}

## Source Files
{file_contents}

## Your Task
1. Identify the exact function(s), method(s), or type definition(s) that need to be changed.
2. Explain WHY each element needs modification.
3. Describe at a high level what the fix should do.

## Output Format
For each element to modify, provide:
- **File**: path/to/file.go
- **Element**: FunctionName or (receiver).MethodName or type TypeName
- **Reason**: Why this needs to change
- **Approach**: High-level description of the fix

Think step by step. Be specific about which lines or logic blocks need changing.
"""
