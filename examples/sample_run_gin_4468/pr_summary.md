---
## PR Title
fix(context): concatenate all RemoteIPHeaders values for ClientIP

## PR Body

### Description
This PR addresses an issue where `ClientIP` incorrectly parses `RemoteIPHeaders` by only considering the first value of a header, rather than concatenating all values as specified by the HTTP RFC. By using `strings.Join(c.Request.Header.Values(key), ",")`, all header values are combined, ensuring accurate client IP determination, especially for headers like `X-Forwarded-For` when multiple instances are present.

### Changes Made
- Modified the `Context.requestHeader` function to use `c.Request.Header.Values(key)` and `strings.Join` to concatenate all values for a given header key.
- Replaced `c.Request.Header.Get(key)` with `strings.Join(c.Request.Header.Values(key), ",")`.

### Related Issue
Resolves #4468

### Testing
Existing unit tests were run using `go test ./...`. The code was checked with `go vet ./...` and built with `go build ./...` to ensure no new issues were introduced. New test cases have been added to `context_test.go` to specifically cover scenarios with multiple `X-Forwarded-For` headers, verifying the correct client IP is returned.
---