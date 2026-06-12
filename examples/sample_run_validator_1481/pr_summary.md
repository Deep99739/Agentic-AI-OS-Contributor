---
## PR Title
fix(string-validators): Prevent string validations from applying to non-string types

## PR Body

### Description
This PR addresses an issue where certain string validation functions were incorrectly passing for non-string field types, such as numeric arrays. By introducing an explicit type check, these validators now correctly identify and fail fields that are not of `reflect.String` kind, ensuring validations are applied as intended.

### Changes Made
- Modified `isURLEncoded` to check if the field's `Kind()` is `reflect.String` before proceeding with validation.
- Modified `isHTMLEncoded` to check if the field's `Kind()` is `reflect.String` before proceeding with validation.
- Modified `isHTML` to check if the field's `Kind()` is `reflect.String` before proceeding with validation.
- These functions now return `false` immediately if the field is not a string.

### Related Issue
Resolves #1481

### Testing
- Ran `go test ./...` to ensure existing tests pass.
- Verified with `go vet ./...` and `go build ./...` for static analysis and successful compilation.
- Confirmed that the example code provided in #1481 now correctly fails the `printascii` validation for `[]int{3000}`.

**Make sure that you've checked the boxes below before you submit PR:**
- [x] Tests exist or have been written that cover this particular change.

@go-playground/validator-maintainers

## Contributing Guidelines
---