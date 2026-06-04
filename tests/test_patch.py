"""Tests for the SEARCH/REPLACE parser and applier."""

import os
import tempfile
from utils.patch import parse_search_replace_blocks, apply_patches


def test_parse_single_block():
    response = """Let me fix this issue.

context.go
```go
<<<<<<< SEARCH
func (c *Context) GetString(key string) string {
    return ""
}
=======
func (c *Context) GetString(key string) string {
    if val, ok := c.Get(key); ok {
        if str, ok := val.(string); ok {
            return str
        }
    }
    return ""
}
>>>>>>> REPLACE
```
"""
    patches = parse_search_replace_blocks(response)
    assert len(patches) == 1
    assert patches[0]["file"] == "context.go"
    assert 'return ""' in patches[0]["search"]
    assert "c.Get(key)" in patches[0]["replace"]


def test_parse_multiple_blocks():
    response = """
router.go
```go
<<<<<<< SEARCH
func old1() {}
=======
func new1() {}
>>>>>>> REPLACE
```

context.go
```go
<<<<<<< SEARCH
func old2() {}
=======
func new2() {}
>>>>>>> REPLACE
```
"""
    patches = parse_search_replace_blocks(response)
    assert len(patches) == 2
    assert patches[0]["file"] == "router.go"
    assert patches[1]["file"] == "context.go"


def test_apply_patch_exact():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.go")
        with open(test_file, "w") as f:
            f.write("package main\n\nfunc hello() {\n\treturn\n}\n")

        patches = [
            {
                "file": "test.go",
                "search": "func hello() {\n\treturn\n}",
                "replace": 'func hello() {\n\tfmt.Println("hello")\n}',
            }
        ]

        results = apply_patches(tmpdir, patches)
        assert len(results) == 1
        assert results[0]["applied"] is True

        with open(test_file) as f:
            content = f.read()
        assert 'fmt.Println("hello")' in content


def test_apply_patch_fuzzy():
    """Test when indentation/whitespace varies slightly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.go")
        with open(test_file, "w") as f:
            # Source file has tabs
            f.write("package main\n\nfunc hello() {\n\treturn\n}\n")

        patches = [
            {
                "file": "test.go",
                # LLM output has spaces instead of tabs
                "search": "func hello() {\n    return\n}",
                "replace": 'func hello() {\n    fmt.Println("hello")\n}',
            }
        ]

        results = apply_patches(tmpdir, patches)
        assert len(results) == 1
        assert results[0]["applied"] is True
        assert results[0].get("fuzzy") is True

        with open(test_file) as f:
            content = f.read()
        assert 'fmt.Println("hello")' in content
