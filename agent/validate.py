"""
Phase 4: Validate candidate patches by running Go build, vet, and test.
Uses standard subprocess calls (no Docker) for minimal setup friction.
"""

import subprocess
import os
from utils.logger import log
from utils.git_ops import GitOps
from utils.patch import apply_patches


class Validator:
    """Scores candidate patches based on Go tooling checks."""

    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.git = GitOps(repo_path)

    def validate_patch(self) -> dict:
        """Run validation checks on the current repo state."""
        results = {
            "gofmt": self._run_gofmt(),
            "build": self._run_command(["go", "build", "./..."]),
            "vet": self._run_command(["go", "vet", "./..."]),
            "test": self._run_command(["go", "test", "-count=1", "-timeout=120s", "./..."]),
        }

        # Calculate a quality score (0 to 10)
        score = 0
        if results["gofmt"]["passed"]:
            score += 1
        if results["build"]["passed"]:
            score += 3  # Build is heavily weighted
        if results["vet"]["passed"]:
            score += 1
        if results["test"]["passed"]:
            score += 5  # Tests passing is the ultimate goal

        results["score"] = score
        return results

    def select_best(self, candidates: list) -> tuple:
        """
        Iterate through candidates, apply each, run validation, and select the best one.
        Returns (best_candidate_dict, list_of_all_results)
        """
        all_results = []
        best_candidate = None
        best_score = -1

        for candidate in candidates:
            log.info(f"Validating candidate {candidate['index']+1}...")

            # 1. Clean state
            self.git.stash_changes()

            try:
                # 2. Apply patches
                apply_results = apply_patches(self.repo_path, candidate["patches"])
                
                # Check if at least one patch applied successfully
                if not any(r.get("applied") for r in apply_results):
                    log.warning(f"  Candidate {candidate['index']+1} failed to apply any patches.")
                    all_results.append({
                        "candidate_index": candidate["index"],
                        "score": 0,
                        "error": "Failed to apply patches to source files"
                    })
                    continue

                # 3. Run validation
                result = self.validate_patch()
                result["candidate_index"] = candidate["index"]
                all_results.append(result)

                # Log outcome
                build_icon = "✅" if result["build"]["passed"] else "❌"
                test_icon = "✅" if result["test"]["passed"] else "❌"
                log.info(
                    f"  Score: {result['score']}/10 (build={build_icon} test={test_icon})"
                )

                # 4. Track best candidate
                if result["score"] > best_score:
                    best_score = result["score"]
                    best_candidate = candidate
                    best_candidate["score"] = result["score"]
                    best_candidate["validation"] = result

                    # Optimization: If perfect score, we can stop early
                    if best_score == 10:
                        log.info("  Perfect score achieved. Stopping validation early.")
                        break

            except Exception as e:
                log.error(f"  Candidate {candidate['index']+1} threw an exception: {e}")
                all_results.append({
                    "candidate_index": candidate["index"],
                    "score": 0,
                    "error": str(e)
                })
            finally:
                # Always restore to clean state before trying the next candidate
                self.git.restore_stash()

        return best_candidate, all_results

    def get_best_effort(self, candidates: list, results: list) -> dict:
        """
        Fallback method if no candidate achieves a perfect score.
        Picks the candidate with the highest score achieved.
        """
        if not candidates or not results:
            return None

        # Sort results by score descending
        scored = [(r.get("score", 0), r.get("candidate_index", 0)) for r in results]
        scored.sort(reverse=True)
        best_idx = scored[0][1]

        # Find the matching candidate
        for c in candidates:
            if c["index"] == best_idx:
                c["score"] = scored[0][0]
                return c
                
        return candidates[0]

    def _run_gofmt(self) -> dict:
        """Check if code is properly formatted and auto-fix it if needed."""
        try:
            result = subprocess.run(
                ["gofmt", "-l", "."],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            unformatted = result.stdout.strip()
            passed = len(unformatted) == 0

            # If it failed the check, try to fix it automatically
            if not passed:
                subprocess.run(
                    ["gofmt", "-w", "."],
                    cwd=self.repo_path,
                    capture_output=True,
                    timeout=30,
                )

            # We consider it passed since we auto-fixed it
            return {"passed": True, "output": "formatted (auto-fixed)" if not passed else "ok"}
            
        except Exception as e:
            return {"passed": False, "output": str(e)}

    def _run_command(self, cmd: list) -> dict:
        """Run a shell command and return pass/fail + truncated output."""
        try:
            result = subprocess.run(
                cmd, cwd=self.repo_path, capture_output=True, text=True, timeout=300
            )
            
            # Combine stdout/stderr and truncate to last 2000 chars to save space
            output = result.stdout + result.stderr
            if len(output) > 2000:
                output = "...[truncated]...\n" + output[-1950:]
                
            return {
                "passed": result.returncode == 0,
                "output": output,
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "output": "TIMEOUT (300s)", "exit_code": -1}
        except Exception as e:
            return {"passed": False, "output": str(e), "exit_code": -1}
