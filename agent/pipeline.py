"""
Main pipeline orchestrator. Runs all 5 phases sequentially.
"""

import os
import json
import time
from datetime import datetime

from agent.ingest import Ingester
from agent.repo_map import RepoMapper
from agent.localize import Localizer
from agent.repair import Repairer
from agent.validate import Validator
from agent.pr_gen import PRGenerator
from utils.logger import log
from utils.git_ops import GitOps


class Pipeline:
    """Orchestrates the 5 phases of the agentic AI contributor."""

    def __init__(self, config: dict):
        self.config = config
        self.output_dir = config.get("output_dir", "./output")
        os.makedirs(self.output_dir, exist_ok=True)

    def run(self, issue_url: str) -> dict:
        """Run the full pipeline on a GitHub issue."""
        start_time = time.time()
        run_log = []

        def log_step(phase: str, message: str, data=None):
            entry = {
                "phase": phase,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "data": data,
            }
            run_log.append(entry)
            log.info(f"[{phase}] {message}")

        try:
            # ── PHASE 1: INGEST ──────────────────────────────
            log_step("INGEST", "Fetching issue and cloning repository...")
            ingester = Ingester(self.config)
            issue_data = ingester.fetch_issue(issue_url)
            repo_path = ingester.clone_repo(issue_data["repo_url"])

            log_step("INGEST", f"Issue #{issue_data['number']}: {issue_data['title']}")
            log_step("INGEST", f"Repository cloned to: {repo_path}")

            with open(os.path.join(self.output_dir, "issue_info.json"), "w") as f:
                json.dump(issue_data, f, indent=2)

            # ── PHASE 1b: REPO MAP ──────────────────────────
            log_step("REPO_MAP", "Generating repository structural map...")
            mapper = RepoMapper(repo_path)
            repo_map = mapper.generate_map()

            with open(os.path.join(self.output_dir, "repo_map.txt"), "w") as f:
                f.write(repo_map)
            log_step("REPO_MAP", f"Repo map generated ({len(repo_map)} chars)")

            # ── PHASE 2: LOCALIZE ────────────────────────────
            log_step("LOCALIZE", "Localizing relevant files and code elements...")
            localizer = Localizer(self.config, repo_path)
            localization = localizer.localize(issue_data, repo_map)

            with open(os.path.join(self.output_dir, "localization.json"), "w") as f:
                json.dump(localization, f, indent=2)
            log_step("LOCALIZE", f"Found {len(localization['files'])} relevant files")

            # ── PHASE 3: REPAIR ──────────────────────────────
            num_candidates = self.config.get("candidates", 3)
            log_step("REPAIR", f"Generating {num_candidates} candidate patches...")
            repairer = Repairer(self.config, repo_path)
            candidates = repairer.generate_patches(
                issue_data, repo_map, localization, num_candidates
            )
            log_step("REPAIR", f"Generated {len(candidates)} candidate patches")

            # ── PHASE 4: VALIDATE ────────────────────────────
            log_step("VALIDATE", "Validating candidate patches...")
            validator = Validator(repo_path)
            best_patch, validation_results = validator.select_best(candidates)

            with open(os.path.join(self.output_dir, "validation_log.json"), "w") as f:
                json.dump(validation_results, f, indent=2)

            if best_patch is None:
                log_step("VALIDATE", "⚠️ No candidate passed perfectly. Using best effort.")
                best_patch = validator.get_best_effort(candidates, validation_results)

            if not best_patch:
                raise RuntimeError("Failed to generate or validate any patches.")

            log_step("VALIDATE", f"Selected best patch (score: {best_patch.get('score', 0)})")

            # Apply the winning patch for real
            git_ops = GitOps(repo_path)
            git_ops.stash_changes()  # Ensure clean slate
            repairer.apply_patch(best_patch)

            # ── PHASE 5: PR GENERATION ───────────────────────
            log_step("PR_GEN", "Generating pull request summary...")
            diff = git_ops.get_diff()

            with open(os.path.join(self.output_dir, "patch.diff"), "w") as f:
                f.write(diff)

            pr_generator = PRGenerator(self.config, repo_path)
            pr_summary = pr_generator.generate(issue_data, diff)

            pr_file = os.path.join(self.output_dir, "pr_summary.md")
            with open(pr_file, "w") as f:
                f.write(pr_summary)

            # Create local branch and commit
            branch_name = f"fix/issue-{issue_data['number']}"
            git_ops.create_branch_and_commit(
                branch_name, f"fix: resolve issue #{issue_data['number']}"
            )
            log_step("PR_GEN", f"Created branch: {branch_name}")

            elapsed = time.time() - start_time
            log_step("DONE", f"Pipeline completed in {elapsed:.1f}s")

            # Save full run log
            with open(os.path.join(self.output_dir, "run_log.json"), "w") as f:
                json.dump(run_log, f, indent=2)

            return {
                "success": True,
                "patch_file": os.path.join(self.output_dir, "patch.diff"),
                "pr_summary_file": pr_file,
                "validation_log": os.path.join(self.output_dir, "validation_log.json"),
                "branch": branch_name,
                "elapsed_seconds": elapsed,
            }

        except Exception as e:
            log.error(f"Pipeline failed: {e}")
            import traceback
            traceback.print_exc()

            with open(os.path.join(self.output_dir, "run_log.json"), "w") as f:
                json.dump(run_log, f, indent=2)

            return {"success": False, "error": str(e)}
