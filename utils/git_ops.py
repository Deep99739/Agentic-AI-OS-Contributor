"""
Git operations: branching, diffing, committing, stashing.
All operations use subprocess to call git directly.
"""

import subprocess
from utils.logger import log


class GitOps:
    """Wrapper around common git CLI operations."""

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def _run(self, args: list, check: bool = False) -> subprocess.CompletedProcess:
        """Run a git command in the repo directory."""
        cmd = ["git"] + args
        return subprocess.run(
            cmd, cwd=self.repo_path, capture_output=True, text=True, timeout=60
        )

    def get_diff(self) -> str:
        """Get the current unstaged diff against HEAD."""
        result = self._run(["diff"])
        if not result.stdout.strip():
            # Also try staged diff
            result = self._run(["diff", "--cached"])
        return result.stdout

    def get_default_branch(self) -> str:
        """Detect whether default branch is 'main' or 'master'."""
        result = self._run(["branch", "-a"])
        branches = result.stdout
        if "main" in branches:
            return "main"
        return "master"

    def create_branch_and_commit(self, branch_name: str, message: str):
        """Create a new branch, stage all changes, and commit."""
        self._run(["checkout", "-b", branch_name])
        self._run(["add", "-A"])
        result = self._run(["commit", "-m", message])
        if result.returncode == 0:
            log.info(f"Created branch '{branch_name}' with commit: {message}")
        else:
            log.warning(f"Commit may have failed: {result.stderr}")

    def stash_changes(self):
        """Discard all working tree changes (checkout + clean)."""
        self._run(["checkout", "."])
        self._run(["clean", "-fd"])

    def restore_stash(self):
        """Alias for stash_changes — restores to clean HEAD state."""
        self.stash_changes()

    def get_changed_files(self) -> list:
        """List files with uncommitted changes."""
        result = self._run(["diff", "--name-only"])
        if result.stdout.strip():
            return result.stdout.strip().split("\n")
        return []
