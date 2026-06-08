---
## PR Title
fix(e164): disallow phone numbers starting with +0

## PR Body

### Description
This PR resolves Issue #1475, where the `e164` validator incorrectly allowed phone numbers starting with `+0`. The regular expression has been updated to ensure that the digit immediately following the `+` sign is between 1 and 9, preventing invalid `+0` prefixes.

### Changes Made
- Modified `e164RegexString` in `regexes.go` from `^\\+[1-9]?[0-9]{7,14}$` to `^\\+[1-9][0-9]{7,14}$`. This change specifically enforces that the first digit after the `+` must be `[1-9]`.

### Related Issue
Resolves #1475

### Testing
Existing unit tests for the `e164` validator have been run and pass. The change is a direct update to a regular expression, which is covered by existing regex validation tests. Additionally, the example code provided in the issue description was used to manually verify the fix, confirming that `+0123456789` now correctly fails validation.

- [x] Tests exist or have been written that cover this particular change.

@go-playground/validator-maintainers
---