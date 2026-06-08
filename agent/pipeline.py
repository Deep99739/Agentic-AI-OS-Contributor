"""
Main pipeline orchestrator. Runs all 5 phases sequentially.
"""

import os
import json
import shutil
import time
import subprocess
from datetime import datetime

from agent.ingest import Ingester
from agent.repo_map import RepoMapper
from agent.localize import Localizer
from agent.repair import Repairer
from agent.validate import Validator
from agent.pr_gen import PRGenerator
from agent.prompts.system import SYSTEM_PROMPT
from utils.logger import log
from utils.git_ops import GitOps


class Pipeline:
    """Orchestrates the 5 phases of the agentic AI contributor."""

    def __init__(self, config: dict):
        self.config = config
        self.output_dir = config.get("output_dir", "./output")
        # Clean output dir to prevent stale artifacts from previous runs
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)
        os.makedirs(self.output_dir, exist_ok=True)

        # Inject the Go-expert system prompt so all LLM calls use it
        if "system_prompt" not in self.config:
            self.config["system_prompt"] = SYSTEM_PROMPT

    def run(self, issue_url: str) -> dict:
        """Run the full pipeline on a GitHub issue."""
        start_time = time.time()
        run_log = []

        def log_step(phase: str, message: str, data=None):
            entry = {
                "phase": phase,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "data": data if data is not None else {},
            }
            run_log.append(entry)
            log.info(f"[{phase}] {message}")
            # Persist log after every step so partial progress is visible
            self._save_log(run_log)

        def _save_artifacts(name: str, content, is_json=True):
            """Save an artifact to the output directory."""
            path = os.path.join(self.output_dir, name)
            with open(path, "w") as f:
                if is_json:
                    json.dump(content, f, indent=2)
                else:
                    f.write(content)
            return path

        try:
            # ── PHASE 1: INGEST ──────────────────────────────
            log_step("INGEST", "Fetching issue and cloning repository...", {
                "issue_url": issue_url,
                "model": self.config.get("model", "unknown"),
                "candidates": self.config.get("candidates", 3),
            })
            ingester = Ingester(self.config)
            issue_data = ingester.fetch_issue(issue_url)
            repo_path = ingester.clone_repo(issue_data["repo_url"])

            # Ensure repo is on clean default branch (handles re-runs)
            git_ops_init = GitOps(repo_path)
            git_ops_init.stash_changes()
            # Delete old fix branches if they exist
            old_branch = f"fix/issue-{issue_data['number']}"
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=repo_path, capture_output=True
            )
            subprocess.run(
                ["git", "checkout", "master"],
                cwd=repo_path, capture_output=True
            )
            subprocess.run(
                ["git", "branch", "-D", old_branch],
                cwd=repo_path, capture_output=True
            )

            # Checkout a specific commit if requested (for testing against pre-fix code)
            checkout_commit = self.config.get("checkout_commit")
            if checkout_commit:
                result = subprocess.run(
                    ["git", "checkout", checkout_commit],
                    cwd=repo_path, capture_output=True, text=True
                )
                if result.returncode == 0:
                    log_step("INGEST", f"Checked out commit: {checkout_commit[:12]}", {
                        "commit": checkout_commit,
                    })
                else:
                    log.warning(f"Failed to checkout {checkout_commit}: {result.stderr}")

            log_step("INGEST", f"Issue #{issue_data['number']}: {issue_data['title']}", {
                "issue_number": issue_data["number"],
                "issue_title": issue_data["title"],
                "labels": issue_data.get("labels", []),
                "comment_count": len(issue_data.get("comments", [])),
            })
            log_step("INGEST", f"Repository cloned to: {repo_path}", {
                "repo_path": repo_path,
                "owner": issue_data.get("owner", ""),
                "repo_name": issue_data.get("repo_name", ""),
            })

            _save_artifacts("issue_info.json", issue_data)

            # ── PHASE 1b: REPO MAP ──────────────────────────
            log_step("REPO_MAP", "Generating repository structural map...", {
                "repo_path": repo_path,
            })

            # Ensure Go module dependencies are available (non-fatal)
            go_mod_ok = False
            try:
                result = subprocess.run(
                    ["go", "mod", "download"],
                    cwd=repo_path, capture_output=True, timeout=180
                )
                go_mod_ok = result.returncode == 0
            except FileNotFoundError:
                log.warning("'go' binary not found. Go validation will be skipped.")
            except Exception:
                log.warning("go mod download failed or timed out. Continuing...")

            mapper = RepoMapper(repo_path)
            repo_map = mapper.generate_map()

            _save_artifacts("repo_map.txt", repo_map, is_json=False)
            log_step("REPO_MAP", f"Repo map generated ({len(repo_map)} chars)", {
                "repo_map_chars": len(repo_map),
                "go_mod_download": "success" if go_mod_ok else "skipped/failed",
            })

            # ── PHASE 2: LOCALIZE ────────────────────────────
            log_step("LOCALIZE", "Localizing relevant files and code elements...", {
                "issue_title": issue_data["title"],
            })
            localizer = Localizer(self.config, repo_path)
            localization = localizer.localize(issue_data, repo_map)

            _save_artifacts("localization.json", localization)
            log_step("LOCALIZE", f"Found {len(localization['files'])} relevant files", {
                "files": localization["files"],
                "element_count": sum(len(f.get("elements", [])) for f in localization.get("file_elements", [])) if "file_elements" in localization else "N/A",
            })

            # ── PHASE 3: REPAIR ──────────────────────────────
            num_candidates = self.config.get("candidates", 3)
            log_step("REPAIR", f"Generating {num_candidates} candidate patches...", {
                "num_candidates": num_candidates,
                "localized_files": localization["files"],
            })
            repairer = Repairer(self.config, repo_path)
            candidates = repairer.generate_patches(
                issue_data, repo_map, localization, num_candidates
            )
            log_step("REPAIR", f"Generated {len(candidates)} candidate patches", {
                "generated_count": len(candidates),
                "patch_files": [
                    [p.get("file", "unknown") for p in c.get("patches", [])]
                    for c in candidates
                ] if candidates else [],
            })

            # ── PHASE 4: VALIDATE ────────────────────────────
            log_step("VALIDATE", "Validating candidate patches...", {
                "candidate_count": len(candidates),
            })
            validator = Validator(repo_path)
            best_patch, validation_results = validator.select_best(candidates)

            _save_artifacts("validation_log.json", validation_results)

            if best_patch is None:
                log_step("VALIDATE", "⚠️ No candidate passed perfectly. Using best effort.", {
                    "validation_results_summary": [
                        {"candidate": i, "score": r.get("score", 0)}
                        for i, r in enumerate(validation_results)
                    ] if isinstance(validation_results, list) else {},
                })
                best_patch = validator.get_best_effort(candidates, validation_results)

            # ── Layer 3 (Defense-in-Depth): Self-Repair Loop ──
            # If best patch scores < 10, try feeding errors back to LLM
            if best_patch and best_patch.get("score", 0) < 10:
                log_step("SELF_REPAIR", "Attempting self-repair (Layer 3)...", {
                    "current_score": best_patch.get("score", 0),
                })

                # Get validation result for error extraction
                val_result = best_patch.get("validation", {})

                # Extract test conventions for the repair prompt
                temp_repairer = Repairer(self.config, repo_path)
                test_conventions = temp_repairer._extract_test_conventions(
                    localization.get("file_contents", {})
                )

                # Extract relevant test context for regression-aware repair
                from agent.test_context import extract_relevant_test_context
                relevant_test_ctx = extract_relevant_test_context(
                    repo_path=repo_path,
                    localized_files=localization.get("files", []),
                    file_contents=localization.get("file_contents", {}),
                    issue_data=issue_data,
                )

                repaired = validator.self_repair(
                    candidate=best_patch,
                    validation_result=val_result,
                    config=self.config,
                    file_contents=localization.get("file_contents", {}),
                    test_conventions=test_conventions,
                    relevant_test_context=relevant_test_ctx,
                )

                if repaired and repaired.get("score", 0) > best_patch.get("score", 0):
                    log_step("SELF_REPAIR", f"✅ Self-repair improved score: {best_patch.get('score', 0)} → {repaired['score']}", {
                        "old_score": best_patch.get("score", 0),
                        "new_score": repaired["score"],
                    })
                    best_patch = repaired
                else:
                    log_step("SELF_REPAIR", "Self-repair did not improve score. Keeping original.", {
                        "original_score": best_patch.get("score", 0),
                    })

            if not best_patch:
                raise RuntimeError("Failed to generate or validate any patches.")

            log_step("VALIDATE", f"Selected best patch (score: {best_patch.get('score', 0)})", {
                "score": best_patch.get("score", 0),
                "build_ok": best_patch.get("build_ok", False),
                "vet_ok": best_patch.get("vet_ok", False),
                "test_ok": best_patch.get("test_ok", False),
                "source_only": best_patch.get("source_only_applied", False),
                "self_repaired": best_patch.get("self_repaired", False),
            })

            # Apply the winning patch for real
            git_ops = GitOps(repo_path)
            git_ops.stash_changes()  # Ensure clean slate
            repairer.apply_patch(best_patch)

            # ── PHASE 5: PR GENERATION ───────────────────────
            log_step("PR_GEN", "Generating pull request summary...", {
                "diff_generation": "in_progress",
            })
            diff = git_ops.get_diff()

            _save_artifacts("patch.diff", diff, is_json=False)

            pr_generator = PRGenerator(self.config, repo_path)
            pr_summary = pr_generator.generate(issue_data, diff)

            pr_file = _save_artifacts("pr_summary.md", pr_summary, is_json=False)

            # Create local branch and commit
            branch_name = f"fix/issue-{issue_data['number']}"
            git_ops.create_branch_and_commit(
                branch_name, f"fix: resolve issue #{issue_data['number']}"
            )
            log_step("PR_GEN", f"Created branch: {branch_name}", {
                "branch_name": branch_name,
                "diff_lines": len(diff.splitlines()),
                "pr_summary_chars": len(pr_summary),
            })

            elapsed = time.time() - start_time
            log_step("DONE", f"✅ Pipeline completed successfully in {elapsed:.1f}s", {
                "elapsed_seconds": round(elapsed, 1),
                "issue_number": issue_data["number"],
                "patch_score": best_patch.get("score", 0),
                "files_modified": len(best_patch.get("patches", [])),
                "branch": branch_name,
            })

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

            elapsed = time.time() - start_time
            log_step("ERROR", f"❌ Failed: {str(e)}", {
                "error": str(e),
                "elapsed_seconds": round(elapsed, 1),
                "error_type": type(e).__name__,
            })

            return {"success": False, "error": str(e)}

    def _save_log(self, run_log: list):
        """Persist the run log after each step for visibility."""
        try:
            with open(os.path.join(self.output_dir, "run_log.json"), "w") as f:
                json.dump(run_log, f, indent=2)
        except Exception:
            pass  # Non-fatal
