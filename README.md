# Agentic AI Contributor for Open-Source Go Projects

An intelligent, pipeline-based system that takes a GitHub issue from an open-source Go project and generates a production-quality code fix with validation.

## Architecture

The system uses a deterministic, multi-stage pipeline inspired by the Agentless approach:

1. **Ingest** — Clone repo, fetch issue via GitHub API
2. **Repo Map** — Generate structural map using `go doc` and file tree
3. **Localize** — Identify relevant files and code elements using LLM
4. **Repair** — Generate 3 candidate patches using SEARCH/REPLACE format
5. **Validate** — Run `go build`, `go vet`, `go test` on each candidate, pick the best
6. **PR Generate** — Create professional PR title and body

## Prerequisites

- Python 3.9+
- Go 1.21+ (for building and testing target repos)
- Git
- An LLM API key (Claude, GPT, or Gemini)

## Setup

```bash
# Clone this repository
git clone <YOUR-REPO-URL>
cd agentic-go-contributor

# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and add your API key (e.g. ANTHROPIC_API_KEY)
```

## Usage

```bash
# Basic usage
python main.py --issue https://github.com/gin-gonic/gin/issues/1234

# With a different model
python main.py --issue https://github.com/spf13/cobra/issues/567 --model gpt-4.1

# With verbose logging
python main.py --issue https://github.com/go-playground/validator/issues/890 --verbose
```

## Output

The system generates the following artifacts in `./output/`:

| File | Description |
|---|---|
| `patch.diff` | The unified diff of all code changes |
| `pr_summary.md` | Generated PR title and body |
| `validation_log.json` | Results of go build, vet, and test |
| `issue_info.json` | Fetched issue metadata |
| `repo_map.txt` | Structural map of the repository |
| `localization.json` | Files and elements identified |
| `run_log.json` | Full execution log |

## Supported Repositories

- `gin-gonic/gin` — HTTP web framework
- `spf13/cobra` — CLI framework  
- `go-playground/validator` — Struct validation
- `golangci/golangci-lint` — Meta-linter

The system is repo-agnostic and works with any Go project.

## Design Decisions

- **Deterministic pipeline over autonomous agents**: Fixed 4-5 LLM calls per run. No infinite loops, predictable cost.
- **Multi-candidate generation**: 3 patches generated at different temperatures, best one selected by test results.
- **SEARCH/REPLACE format**: Surgical edits instead of full-file rewrites. Minimizes hallucination risk.
- **`go doc` for structural mapping**: Provides exported symbol awareness without building a custom AST parser.
- **Subprocess validation (not Docker)**: Zero setup friction. `go build`, `go vet`, `go test` run directly.
- **Model-agnostic via litellm**: Swap between Claude, GPT, Gemini, or local models with a single config change.
