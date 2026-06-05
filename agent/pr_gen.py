"""
Phase 5: Generate a professional PR title and body.
Uses LLM to format the PR according to project conventions if available.
"""

import os
from utils.llm_client import LLMClient
from utils.logger import log
from agent.prompts.pr_summary import PR_SUMMARY_PROMPT


class PRGenerator:
    """Generates a professional PR description based on issue and diff."""

    def __init__(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path
        self.llm = LLMClient(config)

    def generate(self, issue_data: dict, diff: str) -> str:
        """Generate PR title and body."""
        
        # Check for project-specific PR template
        pr_template = ""
        for template_path in [
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/pull_request_template.md",
            "PULL_REQUEST_TEMPLATE.md",
        ]:
            full_path = os.path.join(self.repo_path, template_path)
            if os.path.exists(full_path):
                with open(full_path, "r", errors="ignore") as f:
                    pr_template = f.read()[:2000]
                break
                
        # Check for contributing guidelines
        contributing = ""
        for contrib_path in ["CONTRIBUTING.md", "contributing.md"]:
            full_path = os.path.join(self.repo_path, contrib_path)
            if os.path.exists(full_path):
                with open(full_path, "r", errors="ignore") as f:
                    contributing = f.read()[:2000]
                break

        prompt = PR_SUMMARY_PROMPT.format(
            issue_number=issue_data["number"],
            issue_title=issue_data["title"],
            issue_body=(issue_data.get("body") or "")[:3000],
            diff=diff[:10000],  # Truncate very large diffs
            pr_template=pr_template,
            contributing_guidelines=contributing,
            repo_name=f"{issue_data['owner']}/{issue_data['repo_name']}",
        )

        log.info("Generating PR summary...")
        # Use temperature 0.0 for deterministic, professional output
        response = self.llm.chat(prompt, temperature=0.0)
        return response
