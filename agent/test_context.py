"""
Targeted Test Context Extraction (Phase 2 Improvement 1).

Instead of dumping entire test files (16,000+ lines) into the repair prompt,
this module extracts ONLY the test functions that exercise the code being modified.

Inspired by:
- Otter (ICML 2025): Pass-to-Pass test awareness
- Moatless-Tools: "Insert the right context into a prompt"
- AutoCodeRover (ISSTA 2024): Test-aware localization
"""

import os
import re
from utils.logger import log


def extract_relevant_test_context(
    repo_path: str,
    localized_files: list,
    file_contents: dict,
    issue_data: dict,
    max_chars: int = 8000,
) -> str:
    """
    Extract test functions relevant to the source files being modified.

    Strategy:
    1. For each localized source file, find its companion test file
    2. Extract keywords from the source file and issue
    3. Search the test file for test functions containing those keywords
    4. Return the extracted test functions as a formatted string

    Safeguards:
    - Max 5000 chars total (configurable)
    - If > 5 test functions match, keywords are too generic → skip
    - Only searches companion test files, not the entire repo
    - Graceful fallback: returns empty string if nothing found
    """
    all_test_context = []

    # Separate source files from test files
    source_files = [f for f in localized_files if not f.endswith("_test.go")]

    for source_file in source_files:
        # 1. Find companion test file
        test_file = _find_companion_test_file(repo_path, source_file)
        if not test_file:
            continue

        # 2. Extract keywords from the source file being modified + issue
        keywords = _extract_keywords_from_context(
            source_file, file_contents.get(source_file, ""), issue_data
        )
        if not keywords:
            continue

        # 3. Read the test file
        test_path = os.path.join(repo_path, test_file)
        if not os.path.exists(test_path):
            continue

        with open(test_path, "r", errors="ignore") as f:
            test_content = f.read()

        # 4. Extract matching test functions using PROGRESSIVE NARROWING
        # Instead of searching with all keywords at once (which matches too broadly
        # when generic keywords like "regex" are included), try keywords from most
        # specific to least specific, stopping when we get a manageable number.
        matching_tests = []
        
        # Try each keyword individually, from most specific (issue-derived) first
        for kw in keywords:
            kw_matches = _find_test_functions(test_content, [kw])
            if 1 <= len(kw_matches) <= 5:
                # This keyword gives a precise match — use it
                for m in kw_matches:
                    if m not in matching_tests:
                        matching_tests.append(m)
        
        # If no single keyword was specific enough, try combining issue keywords only
        if not matching_tests and keywords:
            # Use just the first 3 most specific (issue-derived) keywords together
            specific = keywords[:3]
            matching_tests = _find_test_functions(test_content, specific)
        
        # Final safeguard: cap at 5 most relevant
        if len(matching_tests) > 5:
            # Prefer tests whose name contains issue keywords
            def relevance_score(m):
                name_lower = m[0].lower()
                return sum(1 for kw in keywords[:5] if kw in name_lower)
            matching_tests.sort(key=relevance_score, reverse=True)
            matching_tests = matching_tests[:5]

        if not matching_tests:
            continue

        log.info(
            f"  Test context: Found {len(matching_tests)} relevant test(s) for {source_file}"
        )

        for func_name, func_body, line_num in matching_tests:
            # Deduplicate: same test file may be found for multiple source files
            entry = f"--- {func_name} ({test_file}:L{line_num}) ---\n{func_body}"
            if entry not in all_test_context:
                all_test_context.append(entry)

    if not all_test_context:
        return ""

    # Sort by relevance: tests whose names contain issue keywords go first
    issue_text = f"{issue_data.get('title', '')} {issue_data.get('body', '')}".lower()
    def sort_by_relevance(entry):
        # Extract test name from the entry
        name = entry.split("(")[0].replace("--- ", "").strip()
        # Count how many issue words appear in the test name
        name_lower = name.lower()
        return sum(1 for word in issue_text.split() if len(word) > 4 and word in name_lower)
    all_test_context.sort(key=sort_by_relevance, reverse=True)

    # Join and cap at max_chars (increased to 8000 to avoid truncating critical tests)
    result = "\n\n".join(all_test_context)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n... [truncated]"

    return result


def _find_companion_test_file(repo_path: str, source_file: str) -> str:
    """
    Find the test file companion for a Go source file.

    Go convention: foo.go → foo_test.go (same directory)
    Some projects use a single large test file: validator_test.go
    """
    # Direct companion: regexes.go → regexes_test.go
    base, ext = os.path.splitext(source_file)
    direct_test = base + "_test" + ext
    if os.path.exists(os.path.join(repo_path, direct_test)):
        return direct_test

    # Look for any _test.go in the same directory
    source_dir = os.path.dirname(source_file)
    full_dir = os.path.join(repo_path, source_dir) if source_dir else repo_path

    if not os.path.isdir(full_dir):
        return None

    test_files = []
    for f in os.listdir(full_dir):
        if f.endswith("_test.go"):
            test_path = os.path.join(source_dir, f) if source_dir else f
            test_files.append(test_path)

    if not test_files:
        return None

    # Prefer the largest test file (likely the main one)
    test_files.sort(
        key=lambda f: os.path.getsize(os.path.join(repo_path, f)), reverse=True
    )
    return test_files[0]


def _extract_keywords_from_context(
    source_file: str, source_content: str, issue_data: dict
) -> list:
    """
    Extract search keywords from:
    1. The source file name (e.g., regexes.go → "regex")
    2. Constants/variables/functions defined in the source
    3. The issue title and body (backtick-quoted identifiers)
    """
    keywords = set()
    issue_keywords_set = set()  # Track issue-derived keywords separately for priority

    # From filename: regexes.go → "regex", "regexes"
    basename = os.path.splitext(os.path.basename(source_file))[0]
    keywords.add(basename.lower())
    # Singular form: regexes → regex
    if basename.endswith("es"):
        keywords.add(basename[:-2].lower())
    elif basename.endswith("s"):
        keywords.add(basename[:-1].lower())

    # From source content: extract Go identifier names
    # 1. Match const/var/func declarations: func cronRegex()
    identifiers = re.findall(
        r'(?:const|var|func)\s+([a-zA-Z_]\w*)', source_content
    )
    # 2. Match assignments inside const/var blocks: cronRegexString = `...`
    identifiers += re.findall(
        r'^\s+([a-zA-Z_]\w*)\s+(?:=|string)', source_content, re.MULTILINE
    )
    # 3. Match CamelCase identifiers with common suffixes
    identifiers += re.findall(
        r'\b([a-z][a-zA-Z]*(?:Regex|String|Pattern|Validator|Format)\w*)\b', source_content
    )

    for ident in identifiers:
        if len(ident) > 4:
            keywords.add(ident.lower())
            parts = re.findall(r'[A-Z][a-z]+|[a-z]+', ident)
            for part in parts:
                if len(part) > 3:
                    keywords.add(part.lower())

    # From issue: backtick-quoted code (HIGH PRIORITY)
    issue_text = f"{issue_data.get('title', '')} {issue_data.get('body', '')}"
    backtick_code = re.findall(r'`([^`\s]+)`', issue_text)
    for code in backtick_code:
        clean = code.strip("()").split(".")[-1]
        if len(clean) > 3:
            issue_keywords_set.add(clean.lower())
            parts = re.findall(r'[A-Z][a-z]+|[a-z]+', clean)
            for part in parts:
                if len(part) > 3:
                    issue_keywords_set.add(part.lower())

    # From issue: camelCase identifiers in plain text (HIGH PRIORITY)
    camel_case_ids = re.findall(r'\b([a-z][a-zA-Z]+(?:[A-Z][a-z]+)+)\b', issue_text)
    for ident in camel_case_ids:
        if len(ident) > 4:
            issue_keywords_set.add(ident.lower())
            parts = re.findall(r'[A-Z][a-z]+|[a-z]+', ident)
            for part in parts:
                if len(part) > 3:
                    issue_keywords_set.add(part.lower())

    # From issue title: meaningful words (HIGH PRIORITY)
    title_words = re.findall(r'\b([a-zA-Z]{4,})\b', issue_data.get('title', ''))
    stop_words = {'that', 'with', 'from', 'this', 'have', 'been',
                  'will', 'does', 'should', 'could', 'would',
                  'validator', 'accepts', 'arbitrary', 'strings',
                  'containing', 'substring', 'like'}
    for word in title_words:
        if word.lower() not in stop_words:
            issue_keywords_set.add(word.lower())

    # Filter out very common Go keywords that match everything
    noise = {
        "string", "error", "return", "func", "test", "type",
        "struct", "interface", "package", "import", "main",
        "true", "false", "validate", "validator", "value",
        "compile", "lazy",
    }
    issue_keywords_set = issue_keywords_set - noise
    keywords = keywords - noise

    # ── Priority: issue-derived keywords first, then source-derived ──
    # This prevents 100+ regex constants in regexes.go from flooding out
    # the critical issue keyword "cron"
    source_only = keywords - issue_keywords_set

    result = list(issue_keywords_set)[:10] + list(source_only)[:5]
    return result[:15]


def _find_test_functions(test_content: str, keywords: list) -> list:
    """
    Find Go test functions that contain any of the keywords.

    Returns: list of (func_name, func_body, line_number) tuples
    """
    # Parse all test functions from the file
    test_functions = _parse_go_test_functions(test_content)

    # Search for keyword matches
    matching = []
    for func_name, func_body, line_num in test_functions:
        search_text = (func_name + " " + func_body).lower()
        for kw in keywords:
            if kw in search_text:
                matching.append((func_name, func_body, line_num))
                break  # Don't double-count

    return matching


def _parse_go_test_functions(content: str) -> list:
    """
    Parse Go test functions from file content.

    Uses boundary-based splitting (func Test... to next func) instead of
    brace-counting, because Go test data often contains unmatched braces
    inside backtick strings (e.g., `{]`) that break brace-counting.

    Returns: list of (func_name, func_body, line_number) tuples
    """
    results = []
    lines = content.split("\n")

    # First pass: find all test function start lines
    func_starts = []
    for i, line in enumerate(lines):
        match = re.match(r'^func\s+(Test\w+)\s*\(', line)
        if match:
            func_starts.append((i, match.group(1)))

    # Second pass: extract function bodies between boundaries
    for idx, (start_i, func_name) in enumerate(func_starts):
        # End is either the next func or end of file
        if idx + 1 < len(func_starts):
            end_i = func_starts[idx + 1][0]
        else:
            end_i = len(lines)

        # Walk backwards from end to find the closing } of this function
        # (skip blank lines between functions)
        actual_end = end_i - 1
        while actual_end > start_i and lines[actual_end].strip() == "":
            actual_end -= 1

        func_lines = lines[start_i:actual_end + 1]
        start_line = start_i + 1  # 1-indexed

        # Cap at 100 lines to avoid huge functions
        if len(func_lines) <= 100:
            func_body = "\n".join(func_lines)
        else:
            truncated = "\n".join(func_lines[:80])
            truncated += f"\n    // ... ({len(func_lines) - 80} more lines)\n}}"
            func_body = truncated

        results.append((func_name, func_body, start_line))

    return results

