---
## PR Title
fix(help): allow help command to ignore unknown flags for subcommands

## PR Body

### Description
This PR addresses an issue where the `help` command would fail if flags intended for a subcommand were present on the command line (e.g., `prog help sub --myflag`). By configuring the `help` command to ignore unknown flags, it can now correctly display help for the target subcommand without erroring out on flags it doesn't own.

### Changes Made
- Configured the `helpCommand` within `ExecuteC` to set `FParseErrWhitelist.UnknownFlags = true`. This ensures the `help` command's flag parsing ignores flags not defined on itself, allowing them to be passed through to the intended subcommand's help context.

### Related Issue
Resolves #2155

### Testing
The changes were verified by running `make test` to ensure all existing tests pass. Additionally, `go vet ./...` and `go build ./...` were run to confirm code quality and successful compilation. Manual testing confirmed the reported issue is resolved, with `prog help sub --myflag` now correctly displaying help for `sub`.
---