# GitHub Transport

Terms resolved through grill-with-docs session.

## GitHub Transport

How the system reaches GitHub:

- `GITHUB_TRANSPORT=auto` — probe MCP first; fall back to `gh` CLI; error if neither available
- `GITHUB_TRANSPORT=mcp` — require MCP; error if unavailable
- `GITHUB_TRANSPORT=cli` — require `gh` CLI; error if unavailable

The transport model is independent of how credentials are supplied (PAT). MCP availability is probed once per run and cached.

Token resolution: `GITHUB_TOKEN` (project) takes precedence over `OpenCode_Github_Token` (system-managed).
