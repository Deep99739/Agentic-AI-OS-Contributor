---
## PR Title
fix(response_writer): prevent panic in Hijack and CloseNotify with http.TimeoutHandler

## PR Body

### Description
This PR addresses an issue where `responseWriter.Hijack()` and `responseWriter.CloseNotify()` would panic if the underlying `http.ResponseWriter` did not implement `http.Hijacker` or `http.CloseNotifier`, respectively. This commonly occurs when using `http.TimeoutHandler`. The fix introduces safe type assertions, returning `nil` or `http.ErrNotSupported` to prevent panics, consistent with the existing `Flush()` behavior.

### Changes Made
- Modified `responseWriter.Hijack()` to use a type assertion with an `ok` check, returning `nil, nil, http.ErrNotSupported` if the underlying writer is not an `http.Hijacker`.
- Modified `responseWriter.CloseNotify()` to use a type assertion with an `ok` check, returning `nil` if the underlying writer is not an `http.CloseNotifier`.
- Updated `TestResponseWriterHijack` to verify the new non-panicking behavior and the correct error/nil returns.

### Related Issue
Resolves #4638

### Testing
The changes were tested by:
- Running `go test ./...` to ensure all existing and new tests pass.
- Running `go vet ./...` for static analysis.
- Running `go build ./...` to confirm successful compilation.
The `TestResponseWriterHijack` test case was specifically updated to cover the scenarios where the underlying writer does not implement `http.Hijacker` or `http.CloseNotifier`, asserting the expected error and nil returns instead of panics.
---