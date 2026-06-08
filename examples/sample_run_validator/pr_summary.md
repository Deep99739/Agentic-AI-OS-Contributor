---
## PR Title
fix(examples): prevent index out of range panic in struct-level example

## PR Body

### Description
This PR addresses issue #1237, which reported an "index out of range" panic in the `Gender.String()` method within the `_examples/struct-level/main.go` file. The panic occurred because the `gender` enum value (1, 2, 3) was directly used as an index for a 0-indexed array `terms`, leading to an out-of-bounds access.

### Changes Made
- Modified `_examples/struct-level/main.go` to adjust the array index calculation in the `Gender.String()` method from `terms[gender]` to `terms[gender-1]`.

### Related Issue
Resolves #1237

### Testing
The fix was verified by running the `_examples/struct-level/main.go` example locally to confirm it executes without panicking. Standard Go tooling commands `go test ./...`, `go vet ./...`, and `go build ./...` were also executed to ensure no regressions or new issues were introduced.
---