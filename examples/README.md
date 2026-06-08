# Example Pipeline Outputs

This directory contains pre-generated sample outputs from running the agentic AI contributor against real GitHub issues. These are provided so evaluators can review output quality without running the system.

## Sample Runs

### `sample_run/` — gin-gonic/gin #3942
- **Issue**: Checksum mismatch verification
- **Score**: 10/10 (build ✅, vet ✅, test ✅)
- **Patch**: Added `FrameworkVersion` field to `Engine` struct
- **Files**: Complete pipeline output (issue_info, repo_map, localization, patch, PR summary, validation log, run log)

### `sample_run_validator/` — go-playground/validator #1237
- **Issue**: Panic in struct-level example (array index off-by-one)
- **Score**: 10/10 (build ✅, vet ✅, test ✅)
- **Patch**: Fixed `Gender.String()` array index calculation
- **Files**: Complete pipeline output

### `sample_run_cobra/` — spf13/cobra #2122
- **Issue**: Remove repetitive words in documentation
- **Score**: 5/10 (build ✅, vet ✅, test ❌ due to local macOS `dyld` issue)
- **Patch**: 4 edits to `command.go` comments
- **Files**: Partial output (localization completed, patch interrupted)

## Output File Reference

| File | Description |
|---|---|
| `issue_info.json` | Fetched issue metadata from GitHub API |
| `repo_map.txt` | Structural map (file tree + `go doc` output) |
| `localization.json` | Identified files and code elements |
| `patch.diff` | Unified diff of all code changes |
| `pr_summary.md` | Generated PR title and body |
| `validation_log.json` | Results of `go build`, `go vet`, `go test` |
| `run_log.json` | Full timestamped execution log |
