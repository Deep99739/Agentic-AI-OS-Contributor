"""
Phase 3: Generate multiple candidate patches using SEARCH/REPLACE blocks.
Falls back to reading source files directly if localization didn't find them.
"""

import os
from utils.llm_client import LLMClient
from utils.patch import parse_search_replace_blocks, apply_patches
from utils.logger import log
from agent.prompts.repair import REPAIR_PROMPT
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

        file_contents_str = ""
        for fpath, content in file_contents.items():
            # Include line numbers for precise SEARCH block targeting
            lines = content.split("\n")
            numbered = "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(lines))
            file_contents_str += f"\n\n--- FILE: {fpath} ---\n```go\n{numbered}\n```\n"

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
                log.debug(f"  Raw response for debugging:\n{response[:2000]}")

        return candidates

    def apply_patch(self, candidate: dict) -> list:
        """
        Apply a candidate's patches to the actual files in the repository.
        Returns a list of application results.
        """
        return apply_patches(self.repo_path, candidate["patches"])

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

