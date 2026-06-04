"""
Fetch GitHub issue details via the GitHub REST API.
Supports authenticated requests (via GITHUB_TOKEN) for higher rate limits.
"""

import os

try:
    import requests
except ImportError:
    requests = None


def fetch_github_issue(owner: str, repo: str, issue_number: int) -> dict:
    """
    Fetch issue details from the GitHub REST API.

    Args:
        owner: Repository owner (e.g., "gin-gonic")
        repo: Repository name (e.g., "gin")
        issue_number: Issue number

    Returns:
        dict with keys: title, body, labels, comments_text, state, html_url, etc.

    Raises:
        ImportError: If the 'requests' package is not installed.
        requests.HTTPError: If the API call fails.
    """
    if requests is None:
        raise ImportError("requests is required. Install with: pip install requests")

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Use token if available (rate limit: 60 → 5000 req/hr)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    # Fetch the issue
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    issue = resp.json()

    # Fetch comments for additional context (up to 5)
    comments_text = []
    if issue.get("comments", 0) > 0:
        comments_url = f"{url}/comments"
        resp = requests.get(comments_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            for comment in resp.json()[:5]:
                body = comment.get("body", "")
                author = comment.get("user", {}).get("login", "unknown")
                comments_text.append(f"**@{author}**: {body}")

    issue["comments_text"] = comments_text
    return issue
