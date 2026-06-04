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
        # A line ending in .go that isn't inside a code fence
        if (
            line.endswith(".go")
            and not line.startswith("```")
            and not line.startswith("//")
        ):
            path = line.strip("`").strip('"').strip("'").strip()
            path = re.sub(r"^[\-\*\d\.\s]+", "", path).strip()
            if path and ("/" in path or path.endswith(".go")):
                current_file = path.lstrip("./")

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
                patches.append(
                    {
                        "file": current_file,
                        "search": "\n".join(search_lines),
                        "replace": "\n".join(replace_lines),
                    }
                )

        i += 1

    return patches


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
        else:
            msg = f"Search text not found in {patch['file']}"
            results.append({"file": patch["file"], "applied": False, "error": msg})
            log.warning(f"  ❌ Could not apply patch to {patch['file']}: search text not found")

    return results


def _try_fuzzy_apply(
    file_path: str, content: str, search: str, replace: str
) -> bool:
    """
    Try to apply a patch with minor whitespace normalization.
    Strips trailing whitespace from each line before comparing.
    """

    def normalize(s: str) -> str:
        return "\n".join(line.rstrip() for line in s.split("\n"))

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
            if content_lines[i + j].rstrip() != sl.rstrip():
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
