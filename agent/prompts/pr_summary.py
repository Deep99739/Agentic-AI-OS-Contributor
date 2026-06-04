PR_SUMMARY_PROMPT = """You are writing a pull request for the open-source Go project `{repo_name}`.

## Issue Being Fixed
**Issue #{issue_number}**: {issue_title}

**Description**:
{issue_body}

## Code Changes (diff)
```diff
{diff}
```

## Project PR Template
{pr_template}

## Contributing Guidelines
{contributing_guidelines}

## Your Task
Generate a professional PR title and body. The output should be in this exact format:

---
## PR Title
[Write a concise PR title following conventional commit format, e.g., "fix(context): resolve nil pointer in JSON binding"]

## PR Body

### Description
[2-3 sentences explaining what this PR does and why]

### Changes Made
[Bullet list of specific changes]

### Related Issue
Resolves #{issue_number}

### Testing
[Describe what testing was done - mention go test, go vet, go build]
---

Rules:
- Follow the project's PR template if provided.
- Use the conventional commit format for the title if the project uses it.
- Be concise but thorough.
- Mention the issue number with "Resolves #N" to auto-close the issue.
- Don't add unnecessary fluff. Be professional and direct.
"""
