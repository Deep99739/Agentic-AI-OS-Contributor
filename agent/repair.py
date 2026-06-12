"""
Phase 3: Generate multiple candidate patches using SEARCH/REPLACE blocks.
Falls back to reading source files directly if localization didn't find them.
Includes Architect/Editor two-call fallback for complex issues where the LLM
spends all output tokens on analysis without generating code.
"""

import os
from utils.llm_client import LLMClient
from utils.patch import parse_search_replace_blocks, apply_patches
from utils.logger import log
from agent.prompts.repair import REPAIR_PROMPT, PLAN_PROMPT, EDITOR_PROMPT
from agent.test_context import extract_relevant_test_context


class Repairer:
    """Generates and parses candidate code patches."""

    def __init__(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path
        self.llm = LLMClient(config)

    def generate_patches(
        self,
        issue_data: dict,
        repo_map: str,
        localization: dict,
        num_candidates: int = 3,
    ) -> list:
        """
        Generate multiple candidate patches via LLM at varying temperatures.
        Returns a list of candidate dictionaries.
        """
        candidates = []

        # Build the code context string for the LLM
        file_contents = localization.get("file_contents", {})

        # Safety check: if localization returned nothing, warn loudly
        if not file_contents:
            log.warning("No file contents from localization — repair will work with repo map only.")
            log.warning("This may produce less accurate patches.")

        # Smart windowing: For large files, extract targeted windows around
        # the element-localized functions instead of blindly truncating.
        # This prevents the critical failure where the target function is
        # beyond the truncation boundary (e.g., line 1835 of 3116 in baked_in.go).
        element_analysis = localization.get("elements", "")
        file_contents_str = self._build_smart_file_context(
            file_contents, element_analysis
        )

        # Layer 1 (Defense-in-Depth): Extract test conventions from the repo
        test_conventions = self._extract_test_conventions(file_contents)

        # Improvement 1 (Phase 2): Extract relevant test functions
        # Instead of dumping 16,000+ line test files, extract ONLY the test
        # functions that exercise the code being modified.
        relevant_test_cases = extract_relevant_test_context(
            repo_path=self.repo_path,
            localized_files=localization.get("files", []),
            file_contents=file_contents,
            issue_data=issue_data,
        )
        if relevant_test_cases:
            log.info(f"  Test context: {len(relevant_test_cases)} chars of relevant test cases injected")
        else:
            relevant_test_cases = "No specific test cases found for the modified code. Ensure your fix preserves all existing behavior."

        for i in range(num_candidates):
            log.info(f"Generating candidate patch {i+1}/{num_candidates}...")

            # Vary temperature for diversity: 0.0, 0.2, 0.4...
            # The first candidate (0.0) is the most greedy/deterministic
            temperature = 0.0 + (i * 0.2)

            prompt = REPAIR_PROMPT.format(
                issue_title=issue_data["title"],
                issue_body=(issue_data.get("body") or "")[:5000],
                element_analysis=localization.get("elements", "")[:3000],
                file_contents=file_contents_str[:40000],  # ~10k tokens max
                repo_map_snippet=repo_map[:5000],
                test_conventions=test_conventions,
                relevant_test_cases=relevant_test_cases,
            )

            # Generate fix
            response = self.llm.chat(prompt, temperature=temperature)
            log.debug(f"Candidate {i+1} raw response (first 500 chars): {response[:500]}")

            # Extract SEARCH/REPLACE blocks
            patches = parse_search_replace_blocks(response)

            if patches:
                candidates.append(
                    {
                        "index": i,
                        "patches": patches,
                        "raw_response": response,
                        "temperature": temperature,
                    }
                )
                log.info(f"  Candidate {i+1}: {len(patches)} edit(s) parsed")
                # Log which files each patch targets
                for p in patches:
                    log.debug(f"    → {p.get('file', 'unknown')}: SEARCH {len(p.get('search', ''))} chars → REPLACE {len(p.get('replace', ''))} chars")
            else:
                log.warning(f"  Candidate {i+1}: No valid SEARCH/REPLACE blocks found")
                # Log enough of the response to diagnose format issues
                log.warning(f"  Raw response (first 1500 chars):\n{response[:1500]}")
                # Check what format the LLM used instead
                if "```diff" in response:
                    log.warning("  → LLM used DIFF format instead of SEARCH/REPLACE")
                elif "<<<<<<" not in response and "SEARCH" not in response:
                    log.warning("  → LLM did NOT include any SEARCH markers at all")
                elif "<<<<<<" in response and "=======" not in response:
                    log.warning("  → LLM included SEARCH marker but missing ======= separator")
                elif "=======" in response and ">>>>>>>" not in response:
                    log.warning("  → LLM included ======= but missing REPLACE marker")

        # ── Architect/Editor Supplement ──
        # ALWAYS run the two-call approach as a supplement to primary candidates.
        # The primary loop often produces candidates that target the "obvious"
        # function (e.g., Traverse), while the plan-guided approach with multi-plan
        # diversity explores non-obvious helpers (e.g., argsMinusFirstX).
        # Running both maximizes diversity and the chance of finding the right fix.
        log.info(f"  Running Architect/Editor supplement ({len(candidates)} primary candidate(s))...")
        fallback_candidates = self._architect_editor_fallback(
            issue_data, file_contents_str, localization, relevant_test_cases
        )
        candidates.extend(fallback_candidates)

        return candidates

    def _architect_editor_fallback(
        self, issue_data: dict, file_contents_str: str,
        localization: dict, relevant_test_cases: str,
    ) -> list:
        """
        Two-call Architect/Editor fallback for complex issues.

        When the LLM spends all output tokens on analysis without generating
        SEARCH/REPLACE blocks, this method separates reasoning from code generation:
          - Call 1 (Architect/Planner): Produce a concise fix plan
          - Call 2 (Editor): Given the plan, output ONLY SEARCH/REPLACE blocks

        This is inspired by:
          - Aider's Architect/Editor mode
          - Agentless's "localize → plan → fix" pipeline
          - SWE-agent's Thought/Action separation
          - OpenHands's "plan first, then edit" workflow
        """
        candidates = []

        # Plan temperatures: vary to get diverse plans targeting different functions.
        # At temp 0.0, the LLM consistently targets the "obvious" function (e.g., Traverse).
        # Higher temps explore non-obvious helpers (e.g., argsMinusFirstX).
        plan_temperatures = [0.0, 0.5, 0.8]

        # Diversity hints for each attempt to push the LLM toward different functions
        diversity_hints = [
            "",  # Attempt 1: no extra hint, use default PLAN_PROMPT
            "\n\nIMPORTANT: Do NOT target the most obvious top-level function. Instead, look at small HELPER functions and UTILITY functions that are called by the main logic. The bug is likely in a helper that makes a wrong assumption. Trace the call chain carefully.",
            "\n\nIMPORTANT: The previous fix attempt targeted the wrong function. Look at the CALLERS and CALLEES — trace backward from the buggy output to find which small function actually produces the incorrect result. Focus on argument manipulation functions, not parsing/traversal functions.",
        ]

        for attempt in range(3):  # 3 attempts with diverse plans
            log.info(f"  Architect/Editor attempt {attempt+1}/3...")

            # ── Call 1: Architect (Plan) — with diversity ──
            plan_prompt = PLAN_PROMPT.format(
                issue_title=issue_data["title"],
                issue_body=(issue_data.get("body") or "")[:5000],
                element_analysis=localization.get("elements", "")[:3000],
                file_contents=file_contents_str,
            ) + diversity_hints[attempt]

            try:
                plan_temp = plan_temperatures[attempt]
                plan_response = self.llm.chat(plan_prompt, temperature=plan_temp)
                log.info(f"    Plan generated ({len(plan_response)} chars, temp={plan_temp})")
                log.debug(f"    Plan: {plan_response[:500]}")
            except Exception as e:
                log.warning(f"    Plan call failed: {e}")
                continue

            # ── Call 2: Editor (Code) ──
            editor_prompt = EDITOR_PROMPT.format(
                fix_plan=plan_response,
                file_contents=file_contents_str,
                relevant_test_cases=relevant_test_cases,
            )

            try:
                editor_temp = 0.0 + (attempt * 0.1)  # Low variance for code generation
                editor_response = self.llm.chat(editor_prompt, temperature=editor_temp)
                log.debug(f"    Editor response ({len(editor_response)} chars)")
            except Exception as e:
                log.warning(f"    Editor call failed: {e}")
                continue

            # Extract SEARCH/REPLACE blocks
            patches = parse_search_replace_blocks(editor_response)

            if patches:
                candidates.append({
                    "index": 100 + attempt,  # Mark as fallback candidates
                    "patches": patches,
                    "raw_response": editor_response,
                    "temperature": editor_temp,
                    "plan_temperature": plan_temp,
                    "method": "architect_editor",
                })
                log.info(f"    ✅ Architect/Editor attempt {attempt+1}: {len(patches)} edit(s) parsed")
                for p in patches:
                    log.debug(f"      → {p.get('file', 'unknown')}: SEARCH {len(p.get('search', ''))} chars")
            else:
                log.warning(f"    ❌ Architect/Editor attempt {attempt+1}: Editor still produced no SEARCH/REPLACE blocks")
                log.warning(f"    Editor response (first 800 chars):\n{editor_response[:800]}")

        if candidates:
            log.info(f"  Architect/Editor fallback produced {len(candidates)} candidate(s)")
        else:
            log.warning("  Architect/Editor fallback also produced 0 candidates")

        return candidates

    def apply_patch(self, candidate: dict) -> list:
        """
        Apply a candidate's patches to the actual files in the repository.
        Returns a list of application results.
        """
        return apply_patches(self.repo_path, candidate["patches"])

    def _build_smart_file_context(
        self, file_contents: dict, element_analysis: str
    ) -> str:
        """
        Build smart file context for the LLM prompt.

        For small files (< 1500 lines): include the entire file with line numbers.
        For large files (≥ 1500 lines): extract targeted windows around the
        functions/elements identified during localization, plus the first 50 lines
        (package, imports, type definitions).

        This prevents the critical failure where the target function is beyond
        a naive truncation boundary. For example, baked_in.go (3,116 lines) has
        the target function requireCheckFieldValue at line 1835, but a 40K char
        truncation only covers ~1049 lines, so the LLM never sees the target.
        """
        MAX_SMALL_FILE_LINES = 2000
        WINDOW_RADIUS = 150  # Lines before/after each target element
        result = ""

        for fpath, content in file_contents.items():
            lines = content.split("\n")
            total_lines = len(lines)

            if total_lines <= MAX_SMALL_FILE_LINES:
                # Small file — include entirely
                numbered = "\n".join(
                    f"{i+1:4d}: {line}" for i, line in enumerate(lines)
                )
                result += f"\n\n--- FILE: {fpath} ({total_lines} lines) ---\n```go\n{numbered}\n```\n"
            else:
                # Large file — extract smart windows
                log.info(f"  Smart windowing {fpath}: {total_lines} lines (too large for full inclusion)")

                # Collect target line numbers from element analysis
                target_lines = self._find_target_lines_in_file(
                    fpath, content, element_analysis
                )

                if not target_lines:
                    # Fallback: if no specific elements found, use first 500 + last 200 lines
                    log.debug(f"    No specific elements found — using head+tail window")
                    target_lines = [250, total_lines - 100]

                # Build windows around each target
                windows = []

                # Always include the header (package, imports, type defs — first 50 lines)
                windows.append((0, min(50, total_lines)))

                for target_line in sorted(set(target_lines)):
                    start = max(0, target_line - WINDOW_RADIUS)
                    end = min(total_lines, target_line + WINDOW_RADIUS)
                    windows.append((start, end))

                # Merge overlapping windows
                merged = self._merge_windows(windows)

                # Build the numbered content with window markers
                parts = []
                for win_start, win_end in merged:
                    if win_start > 0:
                        parts.append(f"\n... (lines {max(1, merged[0][1]+1)}-{win_start} omitted) ...\n")
                    windowed = "\n".join(
                        f"{i+1:4d}: {lines[i]}" for i in range(win_start, min(win_end, total_lines))
                    )
                    parts.append(windowed)

                total_shown = sum(end - start for start, end in merged)
                log.info(f"    Showing {total_shown}/{total_lines} lines across {len(merged)} window(s)")

                result += f"\n\n--- FILE: {fpath} ({total_lines} lines total, {total_shown} shown) ---\n```go\n{''.join(parts)}\n```\n"

        return result

    def _find_target_lines_in_file(
        self, fpath: str, content: str, element_analysis: str
    ) -> list:
        """
        Find target line numbers in a file based on element analysis.
        Looks for function names mentioned in the analysis and finds their
        line numbers in the actual file content.
        
        Also performs CALLEE EXTRACTION: scans the body of each target function
        for calls to other functions in the same file, and adds those as
        additional targets. This ensures helper functions like argsMinusFirstX
        (called from Find) are included in the smart window even when they're
        outside the radius of the primary target.
        """
        import re
        target_lines = []
        lines = content.split("\n")

        # Extract function/method names from element analysis
        func_names = set()

        # Extract Go function names from analysis text
        for match in re.finditer(r'\b(func\s+(?:\([^)]+\)\s+)?(\w+))', element_analysis):
            func_names.add(match.group(2))
        for match in re.finditer(r'\b([a-zA-Z_]\w+)\s*\(', element_analysis):
            func_names.add(match.group(1))

        # Also extract from the file basename being referenced
        basename = os.path.basename(fpath).replace(".go", "").replace("_test", "")

        # Build an index of ALL function definitions in this file
        # Maps function_name -> line_number
        all_funcs = {}
        for i, line in enumerate(lines):
            # Match "func FuncName(" or "func (c *Command) FuncName("
            func_match = re.match(r'\s*func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(', line)
            if func_match:
                all_funcs[func_match.group(1)] = i

        # Find each mentioned function in the file
        primary_targets = []
        for i, line in enumerate(lines):
            for func_name in func_names:
                if f"func {func_name}" in line or ("func (" in line and func_name in line):
                    target_lines.append(i)
                    primary_targets.append((func_name, i))
                    log.debug(f"    Target element '{func_name}' found at line {i+1}")

        # ── CALLEE EXTRACTION ──
        # For each primary target function, scan its body for calls to other
        # functions defined in the same file. Add those callees as targets too.
        callee_names = set()
        for func_name, func_start in primary_targets:
            # Find the end of this function (next func definition or EOF)
            func_end = len(lines)
            for other_name, other_line in all_funcs.items():
                if other_line > func_start and other_line < func_end:
                    func_end = other_line

            # Scan the function body for calls to known functions
            for i in range(func_start, min(func_end, len(lines))):
                for callee_name, callee_line in all_funcs.items():
                    if callee_name != func_name and callee_name in lines[i]:
                        if callee_name not in callee_names:
                            callee_names.add(callee_name)
                            target_lines.append(callee_line)
                            log.info(f"    Callee '{callee_name}' (line {callee_line+1}) called from '{func_name}' — adding to window")

        return target_lines

    @staticmethod
    def _merge_windows(windows: list) -> list:
        """Merge overlapping (start, end) windows."""
        if not windows:
            return []
        sorted_wins = sorted(windows)
        merged = [sorted_wins[0]]
        for start, end in sorted_wins[1:]:
            if start <= merged[-1][1] + 10:  # Allow 10-line gap for merging
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged


    def _extract_test_conventions(self, file_contents: dict) -> str:
        """
        Layer 1 (Defense-in-Depth): Extract test conventions from the project.

        Scans localized files and the repo for _test.go files, extracts their
        import blocks and early function signatures so the LLM can see:
        - Which assertion library is used (testify, go-playground/assert, stdlib)
        - Whether dot imports are used (bare function names vs qualified)
        - Common test helper patterns
        """
        conventions = []
        test_files_checked = set()

        # 1. Check localized files for test files
        for fpath, content in file_contents.items():
            if "_test.go" in fpath:
                test_files_checked.add(fpath)
                header = self._extract_test_header(fpath, content)
                if header:
                    conventions.append(header)

        # 2. If no test files were localized, find the nearest test file in repo
        if not conventions:
            for fpath in file_contents.keys():
                if not fpath.endswith("_test.go"):
                    dir_path = os.path.dirname(os.path.join(self.repo_path, fpath))
                    if os.path.isdir(dir_path):
                        for f in os.listdir(dir_path):
                            if f.endswith("_test.go") and f not in test_files_checked:
                                full_path = os.path.join(dir_path, f)
                                try:
                                    with open(full_path, "r", errors="ignore") as tf:
                                        test_content = tf.read()
                                    rel_path = os.path.relpath(full_path, self.repo_path)
                                    header = self._extract_test_header(rel_path, test_content)
                                    if header:
                                        conventions.append(header)
                                        test_files_checked.add(f)
                                        break  # One test file per directory is enough
                                except Exception:
                                    pass

        if not conventions:
            return "No test files found. Use standard Go testing patterns (testing.T, if-based assertions)."

        return "\n".join(conventions)

    def _extract_test_header(self, fpath: str, content: str) -> str:
        """Extract the first ~40 lines of a test file to capture imports and patterns."""
        lines = content.split("\n")
        header_lines = lines[:40]
        header = "\n".join(header_lines)

        # Detect specific patterns for extra clarity
        notes = []
        if '. "' in header or ".\t\"" in header:
            notes.append("⚠️  This project uses DOT IMPORTS — assertion functions are called as bare names (e.g., Equal(t, a, b)), NOT with a package prefix (e.g., assert.Equal).")
        if "testify" in header:
            notes.append("This project uses testify for assertions.")
        if "go-playground/assert" in header:
            notes.append("This project uses go-playground/assert (NOT testify).")

        result = f"--- Test file: {fpath} (first 40 lines) ---\n{header}\n"
        if notes:
            result += "\n".join(notes) + "\n"
        return result

