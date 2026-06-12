ELEMENT_LOCALIZATION_PROMPT = """You are an expert Go developer. Given a GitHub issue and the source code of relevant files, identify the EXACT functions, methods, or struct definitions that need to be modified.

## GitHub Issue
**Title**: {issue_title}
**Description**:
{issue_body}

## Source Files
{file_contents}

## Your Task

### Step 1: Trace the execution path
Trace the EXACT execution path that produces the buggy output described in the issue. Start from the entry point and follow every function call. Pay special attention to:
- Helper functions and utility functions that the main function delegates to
- Functions that manipulate arguments, flags, or state
- Small functions that might seem correct in isolation but behave wrong in context

### Step 2: Identify the root cause function
The bug often lives in a HELPER or UTILITY function, NOT the main entry point. Don't just pick the most obvious top-level function. Ask yourself:
- Which function ACTUALLY produces the wrong behavior?
- Is there a small helper that makes an incorrect assumption?
- Could a function that works correctly for simple cases fail for edge cases?

### Step 3: List all elements to modify
For each element, provide:
- **File**: path/to/file.go
- **Element**: FunctionName or (receiver).MethodName or type TypeName
- **Line**: Approximate line number
- **Reason**: Why this needs to change
- **Approach**: High-level description of the fix
- **Callers**: Which functions call this element (important for understanding impact)

Think step by step. Be specific about which lines or logic blocks need changing.
"""
