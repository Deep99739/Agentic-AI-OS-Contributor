"""
Parse and apply SEARCH/REPLACE edit blocks from LLM responses.

Expected format from LLM:
    path/to/file.go
    ```go
    <<<<<<< SEARCH
    exact code to find in the file
    =======
    replacement code
    >>>>>>> REPLACE
    ```

The SEARCH block must exactly match existing source code.
The REPLACE block contains the new code that replaces it.
Multiple blocks can target the same file or different files.
"""

import os
import re
from utils.logger import log


def parse_search_replace_blocks(response: str) -> list:
    """
    Parse SEARCH/REPLACE blocks from an LLM response.

    Returns a list of dicts, each with keys: file, search, replace.
    """
    patches = []
    lines = response.split("\n")
    i = 0
    current_file = None

    while i < len(lines):
        line = lines[i].strip()

        # --- Detect file path ---
        # A line containing a .go path that isn't inside a code fence
        if not line.startswith("```") and not line.startswith("//"):
            go_match = re.search(r'([a-zA-Z0-9_\-./]+\.go)', line)
            if go_match:
                path = go_match.group(1).lstrip("./")
                if path:
                    current_file = path

        # --- Detect SEARCH/REPLACE block ---
        if "<<<<<<< SEARCH" in line or "<<<<<<<SEARCH" in line:
            search_lines = []
            replace_lines = []
            in_search = True
            i += 1

            while i < len(lines):
                raw = lines[i]
                stripped = raw.strip()

                if stripped == "=======" or stripped == "=======":
                    in_search = False
                    i += 1
                    continue
                elif ">>>>>>> REPLACE" in stripped or ">>>>>>>REPLACE" in stripped:
                    break
                else:
                    if in_search:
                        search_lines.append(raw)
                    else:
                        replace_lines.append(raw)
                i += 1

            if current_file and search_lines:
                search_text = "\n".join(search_lines)
                replace_text = "\n".join(replace_lines)

                # Strip line numbers if LLM accidentally included them
                # Pattern: "   42: actual code" → "actual code"
                search_text = _strip_line_numbers(search_text)
                replace_text = _strip_line_numbers(replace_text)

                patches.append(
                    {
                        "file": current_file,
                        "search": search_text,
                        "replace": replace_text,
                    }
                )

        i += 1

    return patches


def _strip_line_numbers(text: str) -> str:
    """
    Strip line number prefixes from LLM output.
    Detects patterns like '  42: code' or '42: code' at the start of every line.
    Only strips if ALL non-empty lines match the pattern.
    """
    lines = text.split("\n")
    pattern = re.compile(r'^\s*\d+:\s?(.*)$')

    # Check if all non-empty lines have line numbers
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return text

    all_numbered = all(pattern.match(l) for l in non_empty)
    if not all_numbered:
        return text

    # Strip line numbers but preserve empty lines
    stripped = []
    for line in lines:
        m = pattern.match(line)
        if m:
            stripped.append(m.group(1))
        else:
            stripped.append(line)

    return "\n".join(stripped)


def apply_patches(repo_path: str, patches: list) -> list:
    """
    Apply parsed SEARCH/REPLACE patches to files in the repository.

    Returns a list of result dicts with keys: file, applied, error (optional).
    """
    results = []

    for patch in patches:
        file_path = os.path.join(repo_path, patch["file"])

        if not os.path.exists(file_path):
            msg = f"File not found: {patch['file']}"
            log.warning(msg)
            results.append({"file": patch["file"], "applied": False, "error": msg})
            continue

        with open(file_path, "r") as f:
            content = f.read()

        search_text = patch["search"]
        replace_text = patch["replace"]

        # --- Strategy 1: Exact match ---
        if search_text in content:
            new_content = content.replace(search_text, replace_text, 1)
            with open(file_path, "w") as f:
                f.write(new_content)
            results.append({"file": patch["file"], "applied": True})
            log.info(f"  ✅ Applied patch to {patch['file']}")
            continue

        # --- Strategy 2: Fuzzy match (whitespace-normalized) ---
        applied = _try_fuzzy_apply(file_path, content, search_text, replace_text)
        if applied:
            results.append({"file": patch["file"], "applied": True, "fuzzy": True})
            log.info(f"  ✅ Applied patch to {patch['file']} (fuzzy match)")
            continue

        # --- Strategy 3: Partial match (try matching a subset of search lines) ---
        applied = _try_partial_match(file_path, content, search_text, replace_text)
        if applied:
            results.append({"file": patch["file"], "applied": True, "partial": True})
            log.info(f"  ✅ Applied patch to {patch['file']} (partial match)")
            continue

        msg = f"Search text not found in {patch['file']}"
        results.append({"file": patch["file"], "applied": False, "error": msg})
        log.warning(f"  ❌ Could not apply patch to {patch['file']}: search text not found")
        # Log first 3 lines of search text for debugging
        search_preview = "\n".join(search_text.split("\n")[:3])
        log.debug(f"    Search text preview: {search_preview}")

    return results


def _try_fuzzy_apply(
    file_path: str, content: str, search: str, replace: str
) -> bool:
    """
    Try to apply a patch with whitespace normalization.
    Handles tab ↔ space mismatches (common when LLMs output spaces but source uses tabs)
    and strips trailing whitespace before comparing.
    """

    def normalize(s: str) -> str:
        return "\n".join(line.replace("\t", "    ").rstrip() for line in s.split("\n"))

    norm_content = normalize(content)
    norm_search = normalize(search)

    if norm_search not in norm_content:
        return False

    # Match line-by-line to find the exact position in the original
    content_lines = content.split("\n")
    search_lines = search.strip().split("\n")

    for i in range(len(content_lines) - len(search_lines) + 1):
        match = True
        for j, sl in enumerate(search_lines):
            # Compare with both tab→space normalization and trailing whitespace stripped
            if content_lines[i + j].replace("\t", "    ").rstrip() != sl.replace("\t", "    ").rstrip():
                match = False
                break

        if match:
            new_lines = (
                content_lines[:i]
                + replace.split("\n")
                + content_lines[i + len(search_lines) :]
            )
            with open(file_path, "w") as f:
                f.write("\n".join(new_lines))
            return True

    return False


def _try_partial_match(
    file_path: str, content: str, search: str, replace: str
) -> bool:
    """
    Try matching using a sliding window on the core lines of the search block.
    If the LLM included slightly wrong context lines, we try matching just
    the middle portion (trimming first/last lines).
    """
    search_lines = search.strip().split("\n")
    if len(search_lines) < 3:
        return False  # Too few lines to do partial matching safely

    # Try trimming 1 line from start and/or end
    for trim_start in range(min(2, len(search_lines) - 1)):
        for trim_end in range(min(2, len(search_lines) - trim_start - 1)):
            end_idx = len(search_lines) - trim_end if trim_end > 0 else len(search_lines)
            trimmed_search = "\n".join(search_lines[trim_start:end_idx])

            if trimmed_search in content:
                # Calculate what the replacement should look like
                replace_lines = replace.strip().split("\n")
                # Adjust replacement to match the trimming
                adj_replace = "\n".join(replace_lines[trim_start:len(replace_lines) - trim_end if trim_end > 0 else len(replace_lines)])

                new_content = content.replace(trimmed_search, adj_replace, 1)
                with open(file_path, "w") as f:
                    f.write(new_content)
                return True

    return False
