## PR Title
fix(uuid): Allow uppercase UUIDs in 'uuid' validation tag

## PR Body
## Fixes Or Enhances
This PR fixes an issue where the `uuid` validation tag failed to recognize valid UUIDs containing uppercase hexadecimal characters.

**Make sure that you've checked the boxes below before you submit PR:**
- [x] Tests exist or have been written that cover this particular change.

### Description
This PR addresses Issue #1550 by updating the regular expression for the `uuid` validation tag. Previously, the `uuid` tag incorrectly rejected valid UUIDs when they contained uppercase hexadecimal characters because its regex only matched lowercase `a-f`. This change modifies the regex to correctly accept both lowercase and uppercase hexadecimal characters.

### Changes Made
- Modified the `uUIDRegexString` constant in `regexes.go` to include uppercase hexadecimal characters (`A-F`) in its character sets. Specifically, `[0-9a-f]` was updated to `[0-9a-fA-F]` across the pattern.

### Related Issue
Resolves #1550

### Testing
Existing unit tests for UUID validation were run and passed. The example code provided in Issue #1550 was also used to confirm that uppercase UUIDs now correctly pass validation with the `uuid` tag. Standard `go test ./...`, `go vet ./...`, and `go build ./...` commands were executed to ensure overall project integrity and no regressions.

@go-playground/validator-maintainers

## Contributing Guidelines