"""
Phase 2: Localize the relevant files and code elements for the issue.
Uses a two-stage LLM approach: file-level retrieval → element-level localization.
Falls back to keyword grep when LLM localization returns empty results.
"""

import os
import re
from collections import Counter
import subprocess
from utils.llm_client import LLMClient
from utils.logger import log
from agent.prompts.localize_files import FILE_LOCALIZATION_PROMPT
from agent.prompts.localize_elements import ELEMENT_LOCALIZATION_PROMPT


class Localizer:
    """Finds the files and specific lines/functions to edit."""

    def __init__(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path
        self.llm = LLMClient(config)

    def localize(self, issue_data: dict, repo_map: str) -> dict:
        """
        Two-stage localization:
        1. Find top files
        2. Read those files and find exact elements
        """
        # --- Stage 1: File-level localization ---
        files = self._localize_files(issue_data, repo_map)
        log.info(f"File localization identified {len(files)} files: {', '.join(files)}")

        # Fallback: if LLM returned nothing, use keyword grep results
        if not files:
            log.warning("LLM file localization returned 0 files. Falling back to keyword grep...")
            files = self._fallback_grep_localization(issue_data)
            if files:
                log.info(f"Grep fallback found {len(files)} files: {', '.join(files)}")

        # Read the identified files
        file_contents = {}
        for fpath in files:
            full_path = os.path.join(self.repo_path, fpath)
            if os.path.exists(full_path):
                with open(full_path, "r", errors="ignore") as f:
                    file_contents[fpath] = f.read()

        if not file_contents:
            log.warning("No valid files localized!")
            return {"files": [], "file_contents": {}, "elements": "No files found."}

        # --- Stage 2: Element-level localization ---
        elements = self._localize_elements(issue_data, file_contents)

        return {
            "files": files,
            "file_contents": file_contents,
            "elements": elements,
        }

    def _localize_files(self, issue_data: dict, repo_map: str) -> list:
        """Use LLM to identify the top relevant files."""
        # Quick keyword grep to help the LLM find obscure files
        keywords = self._extract_keywords(issue_data)
        grep_results = self._grep_keywords(keywords)

        prompt = FILE_LOCALIZATION_PROMPT.format(
            repo_map=repo_map[:20000],  # Truncate if massive
            issue_title=issue_data["title"],
            issue_body=(issue_data.get("body") or "")[:5000],
            grep_hints=grep_results[:3000],
        )

        response = self.llm.chat(prompt)
        log.debug(f"LLM file localization raw response:\n{response[:1000]}")
        files = self._parse_file_list(response)

        # Validate that files actually exist in the repo
        valid_files = []
        for f in files:
            # Clean path
            f = f.strip().lstrip("./")
            full_path = os.path.join(self.repo_path, f)
            if os.path.exists(full_path) and f.endswith(".go"):
                valid_files.append(f)
            else:
                log.debug(f"File not found in repo, skipping: {f}")

        if not valid_files and files:
            log.warning(f"LLM suggested {len(files)} files but none exist in repo: {files[:5]}")

        # Limit to top 7 files to avoid blowing up context window later
        return valid_files[:7]

    def _localize_elements(self, issue_data: dict, file_contents: dict) -> str:
        """Use LLM to identify specific functions/structs to modify."""
        # Build a condensed view of file contents with line numbers
        condensed = ""
        for fpath, content in file_contents.items():
            condensed += f"\n\n--- FILE: {fpath} ---\n"
            # Add line numbers for precise element identification
            lines = content.split("\n")
            numbered = "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(lines[:300]))
            condensed += numbered

        prompt = ELEMENT_LOCALIZATION_PROMPT.format(
            issue_title=issue_data["title"],
            issue_body=(issue_data.get("body") or "")[:3000],
            file_contents=condensed[:50000],
        )

        response = self.llm.chat(prompt)
        return response

    def _extract_keywords(self, issue_data: dict) -> list:
        """Extract likely code keywords (CamelCase, snake_case) from issue text."""
        text = f"{issue_data['title']} {issue_data.get('body') or ''}"
        
        # 1. Dotted paths or CamelCase: "Context.Next", "ShouldBindJSON"
        identifiers = re.findall(r"\b[A-Z][a-zA-Z0-9]*(?:\.[A-Z][a-zA-Z0-9]*)*\b", text)
        # 2. snake_case
        identifiers += re.findall(r"\b[a-z][a-zA-Z0-9]*(?:_[a-z][a-zA-Z0-9]*)+\b", text)
        # 3. Backtick-quoted code (usually the most accurate)
        backtick_code = re.findall(r"`([^`\s]+)`", text)
        identifiers += backtick_code
        # 4. Function calls in code blocks: funcName(
        identifiers += re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text)

        # Filter out common English words that look like identifiers
        stop_words = {"Description", "Problem", "Expected", "Version", "Environment",
                      "Source", "Code", "Error", "Operating", "System", "Linux", "Ubuntu"}
        filtered = [i for i in identifiers if len(i) > 2 and i not in stop_words]
        
        counter = Counter(filtered)
        # Return top 15 most common keywords
        return [word for word, _ in counter.most_common(15)]

    def _grep_keywords(self, keywords: list) -> str:
        """Run grep for keyword occurrences in Go source files."""
        results = []
        for kw in keywords[:10]:
            try:
                result = subprocess.run(
                    ["grep", "-rl", "--include=*.go", kw, "."],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.stdout.strip():
                    # Take only the first 5 matching files
                    files = result.stdout.strip().split("\n")[:5]
                    files = [f.lstrip("./") for f in files]
                    results.append(f"Keyword '{kw}' found in: {', '.join(files)}")
            except Exception:
                pass
                
        return "\n".join(results)

    def _fallback_grep_localization(self, issue_data: dict) -> list:
        """Fallback: use keyword grep to find likely relevant files when LLM fails."""
        keywords = self._extract_keywords(issue_data)
        file_scores = Counter()

        for kw in keywords[:10]:
            try:
                result = subprocess.run(
                    ["grep", "-rl", "--include=*.go", kw, "."],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.stdout.strip():
                    for f in result.stdout.strip().split("\n"):
                        f = f.lstrip("./")
                        # Exclude test files and vendor
                        if f.endswith(".go") and "_test.go" not in f and "vendor/" not in f:
                            file_scores[f] += 1
            except Exception:
                pass

        # Return top 5 files by keyword match count
        top_files = [f for f, _ in file_scores.most_common(5)]
        return top_files

    def _parse_file_list(self, response: str) -> list:
        """Parse file paths from LLM response. Handles various formats."""
        files = []
        for line in response.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Try to extract .go file paths from the line
            # Match patterns like: path/to/file.go, `path/to/file.go`, - path/to/file.go
            go_path_match = re.search(r'([a-zA-Z0-9_\-./]+\.go)', line)
            if go_path_match:
                cleaned = go_path_match.group(1)
                if cleaned and cleaned not in files:
                    files.append(cleaned)

        return files
