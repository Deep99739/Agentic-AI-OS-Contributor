"""
Parse and apply SEARCH/REPLACE edit blocks from LLM responses.

5-Layer Defense Matching Pipeline (inspired by open-source research):
  Layer 1: Exact match (baseline)
  Layer 2: Whitespace-normalized match with indent depth re-alignment (enhanced, from Aider)
  Layer 3: SequenceMatcher fuzzy match with sliding window (from Aider's replace_closest_edit_distance)
  Layer 4: Function-scoped matching for Go files (from AutoCodeRover/Codalotl's AST-based scoping)
  Layer 5: Partial trim match (existing fallback)

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
from difflib import SequenceMatcher
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
    Uses a 5-layer defense matching pipeline.

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

        # --- Layer 1: Exact match ---
        if search_text in content:
            new_content = content.replace(search_text, replace_text, 1)
            with open(file_path, "w") as f:
                f.write(new_content)
            results.append({"file": patch["file"], "applied": True, "layer": 1})
            log.info(f"  ✅ Applied patch to {patch['file']} [Layer 1: exact]")
            continue

        # --- Layer 2: Whitespace-normalized match (enhanced with indent depth) ---
        applied = _try_fuzzy_apply(file_path, content, search_text, replace_text)
        if applied:
            results.append({"file": patch["file"], "applied": True, "layer": 2})
            log.info(f"  ✅ Applied patch to {patch['file']} [Layer 2: whitespace-normalized]")
            continue

        # --- Layer 3: SequenceMatcher fuzzy match (from Aider) ---
        applied = _try_sequence_matcher_apply(file_path, content, search_text, replace_text)
        if applied:
            results.append({"file": patch["file"], "applied": True, "layer": 3})
            log.info(f"  ✅ Applied patch to {patch['file']} [Layer 3: SequenceMatcher fuzzy]")
            continue

        # --- Layer 4: Function-scoped matching (from AutoCodeRover) ---
        applied = _try_function_scoped_apply(file_path, content, search_text, replace_text)
        if applied:
            results.append({"file": patch["file"], "applied": True, "layer": 4})
            log.info(f"  ✅ Applied patch to {patch['file']} [Layer 4: function-scoped]")
            continue

        # --- Layer 5: Partial match (trim context lines) ---
        applied = _try_partial_match(file_path, content, search_text, replace_text)
        if applied:
            results.append({"file": patch["file"], "applied": True, "layer": 5})
            log.info(f"  ✅ Applied patch to {patch['file']} [Layer 5: partial trim]")
            continue

        msg = f"Search text not found in {patch['file']}"
        results.append({"file": patch["file"], "applied": False, "error": msg})
        log.warning(f"  ❌ Could not apply patch to {patch['file']}: search text not found (all 5 layers failed)")
        # Log search text for debugging
        search_preview = search_text.split("\n")[:5]
        log.warning(f"    SEARCH text ({len(search_text)} chars, {len(search_text.split(chr(10)))} lines):")
        for sl in search_preview:
            log.warning(f"      |{sl}|")
        # Log first matching attempt in file
        first_search_line = search_text.split("\n")[0].strip()
        content_lines = content.split("\n")
        for ci, cl in enumerate(content_lines):
            if first_search_line and first_search_line in cl:
                log.warning(f"    First search line found at file line {ci+1}:")
                log.warning(f"      FILE: |{cl}|")
                log.warning(f"      SRCH: |{search_text.split(chr(10))[0]}|")
                if ci+1 < len(content_lines) and len(search_text.split("\n")) > 1:
                    log.warning(f"      FILE+1: |{content_lines[ci+1]}|")
                    log.warning(f"      SRCH+1: |{search_text.split(chr(10))[1]}|")
                break

    return results


def _try_fuzzy_apply(
    file_path: str, content: str, search: str, replace: str
) -> bool:
    """
    Layer 2: Whitespace-normalized matching with indent depth re-alignment.

    Handles:
    - Tab ↔ space mismatches (common when LLMs output spaces but source uses tabs)
    - Trailing whitespace differences
    - Indentation depth mismatches (e.g., LLM uses 2 tabs but file uses 1 tab)

    Inspired by Aider's `replace_part_with_missing_leading_whitespace`.
    """

    def normalize(s: str) -> str:
        return "\n".join(line.replace("\t", "    ").rstrip() for line in s.split("\n"))

    norm_content = normalize(content)
    norm_search = normalize(search)

    # Try direct normalized match first
    if norm_search in norm_content:
        return _apply_normalized_match(file_path, content, search, replace)

    # Enhancement: Try with indent depth re-alignment
    # Detect if the search has a consistent extra indent level
    search_lines = search.strip().split("\n")
    content_lines = content.split("\n")

    if not search_lines:
        return False

    first_search_stripped = search_lines[0].strip()
    if not first_search_stripped:
        return False

    # Find the first occurrence of the search's first line (content-wise) in the file
    for ci, cl in enumerate(content_lines):
        if cl.strip() == first_search_stripped:
            # Calculate indent offset between file and search
            file_indent = len(cl) - len(cl.lstrip())
            search_indent = len(search_lines[0]) - len(search_lines[0].lstrip())

            if file_indent != search_indent:
                # Re-align search indentation and try again
                indent_diff = file_indent - search_indent
                realigned_search = _adjust_indentation(search, indent_diff)

                if realigned_search in content:
                    realigned_replace = _adjust_indentation(replace, indent_diff)
                    new_content = content.replace(realigned_search, realigned_replace, 1)
                    with open(file_path, "w") as f:
                        f.write(new_content)
                    log.debug(f"    Indent re-aligned by {indent_diff} chars")
                    return True

    return False


def _apply_normalized_match(
    file_path: str, content: str, search: str, replace: str
) -> bool:
    """Apply a match found through whitespace normalization."""
    content_lines = content.split("\n")
    search_lines = search.strip().split("\n")

    for i in range(len(content_lines) - len(search_lines) + 1):
        match = True
        for j, sl in enumerate(search_lines):
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


def _try_sequence_matcher_apply(
    file_path: str, content: str, search: str, replace: str,
    threshold: float = 0.6
) -> bool:
    """
    Layer 3: SequenceMatcher fuzzy matching (inspired by Aider's replace_closest_edit_distance).

    Slides a window of len(search_lines) across the file content and computes
    a similarity ratio at each position using difflib.SequenceMatcher.
    The position with the highest ratio above the threshold is used.

    This handles:
    - Minor content hallucinations (a few wrong lines among mostly correct ones)
    - Indentation mismatches across all lines
    - Small insertions/deletions in the search block
    """
    content_lines = content.split("\n")
    search_lines = search.strip().split("\n")

    if len(search_lines) < 2:
        return False  # Too short for reliable fuzzy matching

    search_text_stripped = "\n".join(line.strip() for line in search_lines)
    best_ratio = 0.0
    best_start = -1

    # Slide window across file
    window_size = len(search_lines)
    for i in range(len(content_lines) - window_size + 1):
        window = "\n".join(line.strip() for line in content_lines[i:i + window_size])
        ratio = SequenceMatcher(None, search_text_stripped, window).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i

    if best_ratio < threshold or best_start < 0:
        log.debug(f"    SequenceMatcher best ratio: {best_ratio:.3f} (threshold: {threshold}) — no match")
        return False

    log.info(f"    SequenceMatcher found match at line {best_start+1} (ratio: {best_ratio:.3f})")

    # Determine the actual indentation from the file
    actual_first_line = content_lines[best_start]
    search_first_line = search_lines[0]
    file_indent = len(actual_first_line) - len(actual_first_line.lstrip())
    search_indent = len(search_first_line) - len(search_first_line.lstrip())
    indent_diff = file_indent - search_indent

    # Apply replacement with correct indentation
    adjusted_replace = _adjust_indentation(replace, indent_diff)
    replace_lines = adjusted_replace.split("\n")

    new_lines = (
        content_lines[:best_start]
        + replace_lines
        + content_lines[best_start + window_size:]
    )
    with open(file_path, "w") as f:
        f.write("\n".join(new_lines))
    return True


def _try_function_scoped_apply(
    file_path: str, content: str, search: str, replace: str
) -> bool:
    """
    Layer 4: Function-scoped matching for Go files.
    Inspired by AutoCodeRover's AST-based localization and Codalotl's Go AST parsing.

    Parses Go function boundaries and restricts the fuzzy search to
    within each function. This eliminates ambiguity when a file has
    repeated structural patterns (e.g., 20 identical switch-case blocks).

    Strategy:
    1. Parse all function boundaries in the file
    2. For each function, try exact match → then fuzzy match within that scope
    3. If found in any function, apply the replacement
    """
    if not file_path.endswith(".go"):
        return False

    content_lines = content.split("\n")
    search_lines = search.strip().split("\n")

    if len(search_lines) < 2:
        return False

    # Parse Go function boundaries
    functions = _parse_go_function_boundaries(content_lines)

    if not functions:
        return False

    search_first_stripped = search_lines[0].strip()
    search_text_stripped = "\n".join(line.strip() for line in search_lines)

    for func_name, func_start, func_end in functions:
        func_content_lines = content_lines[func_start:func_end]
        func_content = "\n".join(func_content_lines)

        # Quick check: does the first search line even appear in this function?
        if search_first_stripped not in func_content:
            continue

        # Try exact match within this function scope
        search_stripped = search.strip()
        if search_stripped in func_content:
            # Found exact match in this function
            new_func = func_content.replace(search_stripped, replace.strip(), 1)
            new_lines = content_lines[:func_start] + new_func.split("\n") + content_lines[func_end:]
            with open(file_path, "w") as f:
                f.write("\n".join(new_lines))
            log.info(f"    Matched in function '{func_name}' (exact, scoped)")
            return True

        # Try fuzzy match within this function scope
        window_size = len(search_lines)
        best_ratio = 0.0
        best_offset = -1

        for i in range(len(func_content_lines) - window_size + 1):
            window = "\n".join(line.strip() for line in func_content_lines[i:i + window_size])
            ratio = SequenceMatcher(None, search_text_stripped, window).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_offset = i

        if best_ratio >= 0.55 and best_offset >= 0:
            # Found fuzzy match within this function
            abs_start = func_start + best_offset

            # Determine indentation
            actual_first = content_lines[abs_start]
            search_first = search_lines[0]
            indent_diff = (len(actual_first) - len(actual_first.lstrip())) - (len(search_first) - len(search_first.lstrip()))

            adjusted_replace = _adjust_indentation(replace, indent_diff)
            replace_result_lines = adjusted_replace.split("\n")

            new_lines = (
                content_lines[:abs_start]
                + replace_result_lines
                + content_lines[abs_start + window_size:]
            )
            with open(file_path, "w") as f:
                f.write("\n".join(new_lines))
            log.info(f"    Matched in function '{func_name}' (fuzzy ratio: {best_ratio:.3f}, scoped)")
            return True

    return False


def _parse_go_function_boundaries(content_lines: list) -> list:
    """
    Parse Go function/method boundaries from source lines.
    Returns list of (func_name, start_line_idx, end_line_idx).

    Uses brace counting to find function ends.
    Handles:
    - Regular functions: func name(...)
    - Methods: func (r *Type) name(...)
    """
    functions = []
    func_pattern = re.compile(r'^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(')

    i = 0
    while i < len(content_lines):
        match = func_pattern.match(content_lines[i])
        if match:
            func_name = match.group(1)
            func_start = i

            # Count braces to find function end
            brace_count = 0
            found_open = False
            j = i
            while j < len(content_lines):
                line = content_lines[j]
                for ch in line:
                    if ch == '{':
                        brace_count += 1
                        found_open = True
                    elif ch == '}':
                        brace_count -= 1

                if found_open and brace_count == 0:
                    functions.append((func_name, func_start, j + 1))
                    break
                j += 1

            i = j + 1 if found_open and brace_count == 0 else i + 1
        else:
            i += 1

    return functions


def _try_partial_match(
    file_path: str, content: str, search: str, replace: str
) -> bool:
    """
    Layer 5: Partial match — try matching a subset of search lines.
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


def _adjust_indentation(text: str, indent_diff: int) -> str:
    """
    Adjust the indentation of all lines in text by indent_diff characters.
    Positive = add spaces, Negative = remove spaces.
    """
    if indent_diff == 0:
        return text

    lines = text.split("\n")
    adjusted = []
    for line in lines:
        if not line.strip():
            adjusted.append(line)
        elif indent_diff > 0:
            adjusted.append(" " * indent_diff + line)
        else:
            # Remove leading whitespace (up to |indent_diff| chars)
            remove = abs(indent_diff)
            stripped = line
            removed = 0
            while removed < remove and stripped and stripped[0] in ' \t':
                if stripped[0] == '\t':
                    removed += 4  # Count tab as 4 spaces
                else:
                    removed += 1
                stripped = stripped[1:]
            adjusted.append(stripped)

    return "\n".join(adjusted)


def _detect_indent(line: str) -> int:
    """Detect the number of leading whitespace characters (tabs count as 4)."""
    count = 0
    for ch in line:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 4
        else:
            break
    return count
