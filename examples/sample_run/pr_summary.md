---
## PR Title
feat(engine): expose framework version in Engine struct

## PR Body

### Description
This PR introduces a `FrameworkVersion` field to the `Engine` struct, making the current Gin framework version accessible at runtime. This enhancement provides a programmatic way to identify the Gin version being used by an application. While not directly resolving past module checksum issues, having the framework version readily available can aid in verifying the integrity of the Gin dependency and assist in debugging scenarios where module resolution or version identification might be ambiguous, such as those highlighted by checksum mismatches.

### Changes Made
- Added a new `FrameworkVersion` string field to the `Engine` struct.
- Initialized `Engine.FrameworkVersion` with the global `Version` constant during the `New` function call.

### Related Issue
Resolves #3942

### Testing
- `go test ./...` passes.
- `go vet ./...` passes.
- `go build ./...` passes.
- Manually verified that `engine.FrameworkVersion` correctly reflects `gin.Version` after engine creation.
- As this introduces a new feature, documentation in `docs/doc.md` will be added in a follow-up commit or PR, or as part of this PR if deemed necessary by maintainers.
---