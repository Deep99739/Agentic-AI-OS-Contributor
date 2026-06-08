"""
Phase 1: Fetch GitHub issue and clone the repository.
"""

import os
import re
import subprocess
from utils.github_api import fetch_github_issue
from utils.logger import log


class Ingester:
    """Handles fetching issue details and cloning the target repo."""

    def __init__(self, config: dict):
        self.config = config
        self.workspace = config.get("workspace", "./workspace")
        os.makedirs(self.workspace, exist_ok=True)

    def parse_issue_url(self, url: str) -> dict:
        """Parse a GitHub issue URL into owner, repo, issue number."""
        # Handles: https://github.com/owner/repo/issues/123
        pattern = r"github\.com/([^/]+)/([^/]+)/issues/(\d+)"
        match = re.search(pattern, url)
        if not match:
            raise ValueError(f"Invalid GitHub issue URL: {url}")

        return {
            "owner": match.group(1),
            "repo": match.group(2),
            "number": int(match.group(3)),
            "repo_url": f"https://github.com/{match.group(1)}/{match.group(2)}.git",
        }

    def fetch_issue(self, issue_url: str) -> dict:
        """Fetch issue details from GitHub API."""
        parsed = self.parse_issue_url(issue_url)
        issue = fetch_github_issue(parsed["owner"], parsed["repo"], parsed["number"])

        return {
            "url": issue_url,
            "owner": parsed["owner"],
            "repo_name": parsed["repo"],
            "repo_url": parsed["repo_url"],
            "number": parsed["number"],
            "title": issue["title"],
            "body": issue.get("body", ""),
            "labels": [l["name"] for l in issue.get("labels", [])],
            "comments": issue.get("comments_text", []),
        }

    def clone_repo(self, repo_url: str) -> str:
        """Clone the repository. Returns path to cloned repo."""
        # Extract repo name from URL
        repo_name = repo_url.removesuffix(".git").split("/")[-1]
        owner = repo_url.removesuffix(".git").split("/")[-2]
        repo_path = os.path.join(self.workspace, f"{owner}_{repo_name}")

        if os.path.exists(repo_path):
            log.info(f"Repository already exists at {repo_path}, pulling latest...")
            # Ensure we're on a clean main/master branch
            subprocess.run(["git", "checkout", "."], cwd=repo_path, capture_output=True)
            
            # Try main, then master
            res = subprocess.run(["git", "checkout", "main"], cwd=repo_path, capture_output=True)
            if res.returncode != 0:
                subprocess.run(["git", "checkout", "master"], cwd=repo_path, capture_output=True)
                
            subprocess.run(["git", "pull", "--ff-only"], cwd=repo_path, capture_output=True)
        else:
            log.info(f"Cloning {repo_url}...")
            # Shallow clone for speed, but need history if we're doing complex diffs.
            # Using full clone is safer for Go projects (modules).
            result = subprocess.run(
                ["git", "clone", repo_url, repo_path],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Git clone failed: {result.stderr}")

        return repo_path
