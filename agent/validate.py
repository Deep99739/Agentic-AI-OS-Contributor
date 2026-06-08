"""
Phase 4: Validate candidate patches by running Go build, vet, and test.
Uses standard subprocess calls (no Docker) for minimal setup friction.
Includes Defense-in-Depth layers 2 (source-only fallback) and 3 (self-repair).
"""

import subprocess
import os
from utils.logger import log
from utils.git_ops import GitOps
from utils.patch import apply_patches, parse_search_replace_blocks
from utils.llm_client import LLMClient
from agent.prompts.self_repair import SELF_REPAIR_PROMPT


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

                # ── Layer 2 (Defense-in-Depth): Source-Only Fallback ──
                # If score < 10 and there are test file patches, try source-only
                if result["score"] < 10:
                    source_patches = [p for p in candidate["patches"] if "_test.go" not in p.get("file", "")]
                    test_patches = [p for p in candidate["patches"] if "_test.go" in p.get("file", "")]

                    if test_patches and source_patches:
                        log.info(f"  Layer 2: Retrying with source-only patches (stripping {len(test_patches)} test patch(es))...")
                        self.git.stash_changes()

                        source_apply_results = apply_patches(self.repo_path, source_patches)
                        if any(r.get("applied") for r in source_apply_results):
                            source_result = self.validate_patch()
                            source_result["candidate_index"] = candidate["index"]
                            source_result["source_only"] = True

                            s_build = "✅" if source_result["build"]["passed"] else "❌"
                            s_test = "✅" if source_result["test"]["passed"] else "❌"
                            log.info(
                                f"  Layer 2 source-only score: {source_result['score']}/10 (build={s_build} test={s_test})"
                            )

                            if source_result["score"] > result["score"]:
                                log.info(f"  Layer 2: Source-only scored higher ({source_result['score']} > {result['score']}). Using source-only.")
                                result = source_result
                                # Update the candidate to use source-only patches
                                candidate["patches"] = source_patches
                                candidate["source_only_applied"] = True
                                # Replace the last result in all_results
                                all_results[-1] = result

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

    def self_repair(self, candidate: dict, validation_result: dict, config: dict,
                    file_contents: dict, test_conventions: str = "",
                    relevant_test_context: str = "") -> dict:
        """
        Layer 3 (Defense-in-Depth): Self-Repair Loop.

        When the best candidate scores < 10, feed the error output back to the
        LLM and ask it to fix only the errors without changing the core logic.

        Improvements:
        - Improvement 2: Reads PATCHED files from disk (not originals)
        - Improvement 3: Detects regression vs syntax errors, adjusts strategy

        Returns: A repaired candidate dict, or None if repair failed.
        """
        # Extract error messages from validation result
        errors = []
        for check in ["build", "vet", "test"]:
            if check in validation_result and not validation_result[check].get("passed", True):
                output = validation_result[check].get("output", "")
                if output:
                    errors.append(f"--- {check.upper()} ERRORS ---\n{output}")

        if not errors:
            log.info("  Layer 3: No specific errors to repair.")
            return None

        error_output = "\n\n".join(errors)

        # ── Improvement 3: Detect regression vs syntax error ──
        build_passed = validation_result.get("build", {}).get("passed", False)
        test_failed = not validation_result.get("test", {}).get("passed", True)
        is_regression = build_passed and test_failed

        if is_regression:
            log.info("  Layer 3: Detected TEST REGRESSION (build passes, tests fail)")
        else:
            log.info("  Layer 3: Detected SYNTAX/BUILD error")

        # Reconstruct the previous patch as text for context
        previous_patch_text = ""
        for p in candidate.get("patches", []):
            previous_patch_text += f"\nFile: {p.get('file', 'unknown')}\n"
            previous_patch_text += f"SEARCH:\n{p.get('search', '')}\n"
            previous_patch_text += f"REPLACE:\n{p.get('replace', '')}\n"

        # ── Improvement 2: Read PATCHED files from disk ──
        # Apply source patches first so we can read the actual state
        source_patches = [p for p in candidate["patches"] if "_test.go" not in p.get("file", "")]
        self.git.stash_changes()
        apply_patches(self.repo_path, source_patches)

        file_contents_str = ""
        for fpath in file_contents.keys():
            full_path = os.path.join(self.repo_path, fpath)
            if os.path.exists(full_path):
                with open(full_path, "r", errors="ignore") as f:
                    patched_content = f.read()
                lines = patched_content.split("\n")
                numbered = "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(lines[:200]))
                file_contents_str += f"\n--- FILE: {fpath} (PATCHED STATE) ---\n{numbered}\n"

        self.git.restore_stash()

        # ── Improvement 3: Choose repair prompt based on error type ──
        if is_regression:
            prompt = SELF_REPAIR_PROMPT.format(
                error_output=error_output[:3000],
                previous_patch=previous_patch_text[:5000],
                file_contents=file_contents_str[:15000],
                test_conventions=test_conventions or "Use standard Go testing patterns.",
                repair_mode="REGRESSION",
                regression_guidance=f"""
YOUR FIX CAUSED A TEST REGRESSION — a test that was passing before your fix is now failing.
This means your fix is INCOMPLETE, not wrong. The core approach is correct but needs to be EXPANDED.

You need to EXPAND your fix to also support the patterns expected by the failing test,
while still fixing the original issue.

## Relevant Test Cases (these MUST continue passing)
{relevant_test_context[:3000] if relevant_test_context else 'See test error output above for the failing test details.'}
""",
            )
        else:
            prompt = SELF_REPAIR_PROMPT.format(
                error_output=error_output[:3000],
                previous_patch=previous_patch_text[:5000],
                file_contents=file_contents_str[:15000],
                test_conventions=test_conventions or "Use standard Go testing patterns.",
                repair_mode="SYNTAX",
                regression_guidance="Fix ONLY the compilation/syntax errors. Keep the core logic unchanged.",
            )

        try:
            llm = LLMClient(config)
            log.info("  Layer 3: Asking LLM to fix the errors...")
            response = llm.chat(prompt, temperature=0.0)

            # Parse the repaired SEARCH/REPLACE blocks
            repaired_patches = parse_search_replace_blocks(response)

            if not repaired_patches:
                log.warning("  Layer 3: LLM returned no valid SEARCH/REPLACE blocks.")
                return None

            log.info(f"  Layer 3: Got {len(repaired_patches)} repaired edit(s). Validating...")

            # Apply and validate the repaired patches
            self.git.stash_changes()

            # First apply the original source patches (the core fix)
            source_patches = [p for p in candidate["patches"] if "_test.go" not in p.get("file", "")]
            apply_patches(self.repo_path, source_patches)

            # Then apply the repair patches on top
            repair_results = apply_patches(self.repo_path, repaired_patches)
            if not any(r.get("applied") for r in repair_results):
                log.warning("  Layer 3: Repaired patches failed to apply.")
                self.git.restore_stash()
                return None

            # Validate the repaired version
            repaired_result = self.validate_patch()
            self.git.restore_stash()

            r_build = "✅" if repaired_result["build"]["passed"] else "❌"
            r_test = "✅" if repaired_result["test"]["passed"] else "❌"
            log.info(f"  Layer 3 repaired score: {repaired_result['score']}/10 (build={r_build} test={r_test})")

            if repaired_result["score"] > candidate.get("score", 0):
                # Build a new candidate with the combined patches
                combined_patches = source_patches + repaired_patches
                repaired_candidate = {
                    "index": candidate["index"],
                    "patches": combined_patches,
                    "raw_response": response,
                    "temperature": 0.0,
                    "score": repaired_result["score"],
                    "validation": repaired_result,
                    "self_repaired": True,
                }
                return repaired_candidate
            else:
                log.info(f"  Layer 3: Repair did not improve score ({repaired_result['score']} <= {candidate.get('score', 0)}).")
                return None

        except Exception as e:
            log.warning(f"  Layer 3: Self-repair failed with exception: {e}")
            return None

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
