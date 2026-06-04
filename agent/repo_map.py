"""
Generate a compressed structural map of the Go repository.
Uses `find` (for file tree), `go doc` (for symbols), and file content analysis.
"""

import os
import subprocess
from utils.logger import log


class RepoMapper:
    """Creates a textual map of a repository's structure for LLM context."""

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def generate_map(self) -> str:
        """Generate a comprehensive repository map."""
        sections = []

        # 1. Directory tree (Go files only)
        sections.append("## Repository File Tree\n")
        sections.append(self._get_tree())

        # 2. Go doc output (exported symbols)
        sections.append("\n## Exported Symbols (go doc)\n")
        sections.append(self._get_go_doc())

        # 3. Key file summaries (README, CONTRIBUTING)
        for fname in ["README.md", "CONTRIBUTING.md", ".github/PULL_REQUEST_TEMPLATE.md"]:
            fpath = os.path.join(self.repo_path, fname)
            if os.path.exists(fpath):
                sections.append(f"\n## {fname}\n")
                with open(fpath, "r", errors="ignore") as f:
                    content = f.read()[:3000]  # Limit to first 3000 chars
                sections.append(content)

        return "\n".join(sections)

    def _get_tree(self) -> str:
        """Get directory tree showing only .go files."""
        try:
            result = subprocess.run(
                [
                    "find",
                    ".",
                    "-name",
                    "*.go",
                    "-not",
                    "-path",
                    "*/vendor/*",
                    "-not",
                    "-path",
                    "*/.git/*",
                ],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                # Sort the files for deterministic output
                files = sorted(result.stdout.strip().split("\n"))
                return "\n".join(files)
            return "(No Go files found)"
        except Exception as e:
            log.warning(f"Tree generation failed: {e}")
            return "(tree generation failed)"

    def _get_go_doc(self) -> str:
        """Get exported symbols using `go doc` for the top packages."""
        try:
            # List all packages in the module
            result = subprocess.run(
                ["go", "list", "./..."],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return f"(go list failed: {result.stderr.strip()})"

            packages = result.stdout.strip().split("\n")
            # Limit to top 20 packages to avoid blowing up context window
            packages = packages[:20]

            doc_sections = []
            for pkg in packages:
                if not pkg:
                    continue
                pkg_result = subprocess.run(
                    ["go", "doc", "-short", pkg],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if pkg_result.returncode == 0 and pkg_result.stdout.strip():
                    doc_sections.append(f"### {pkg}\n{pkg_result.stdout.strip()}\n")

            if doc_sections:
                return "\n".join(doc_sections)
            return "(no go doc output)"
        except Exception as e:
            log.warning(f"go doc failed: {e}")
            return "(go doc failed)"
