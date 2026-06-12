# Project Scope

This document surfaces the MVP shape, V1 operating assumptions, and V1 non-goals of precision-squad. It is a short, scannable summary for the cascading prompt chain. The canonical public-facing source for this content is `README.md`.

## MVP Shape

The seven-step MVP control loop:

1. Accept a GitHub issue
2. Normalize it into a runnable request
3. Extract the documented local setup and QA contract
4. Execute the repair workflow
5. Collect artifacts and evidence
6. Apply governance
7. Publish a draft PR or a blocked verdict

For the full text, see `README.md:28-36`.

## V1 Operating Assumptions

### Authentication (Credential Supply)
- PAT-only credential supply for GitHub operations

### Transport (How GitHub Operations Are Executed)
- `GITHUB_TRANSPORT=auto|mcp|cli` — see [`instructions/github-transport.md`](./github-transport.md) for transport model details
- CLI/service first
- Filesystem-backed run persistence
- Docs-first execution behind a narrow adapter boundary

For the full text, see `README.md:38-47`.

## V1 Non-Goals

### Authentication
- No GitHub App authentication

### Transport
- No deep repo-specific inference machinery

### Persistence
- No database-backed persistence

### Execution
- No multi-tenant or broad parallel execution

For the full text, see `README.md:49-60`.
