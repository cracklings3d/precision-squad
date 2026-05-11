# Context

Terms resolved through grill-with-docs session.

## Governance Verdicts

- **Approved** — governance says yes. Creates `draft_pr` automatically.
- **Blocked** — governance says no. Creates `requires_review` or `follow_up_issue`. Requires human action before publishing.
- **No provisional verdict.** Provisional quality is now a tag on `ExecutionResult`, not a governance outcome.

## Quality Tag

Attached to `ExecutionResult`. Values:

- `green` — baseline passed, or final matches baseline (no new failures)
- `improved` — baseline failed, final has fewer failures (baseline-tolerant repair)
- `degraded` — new failures introduced by repair

Quality tag is informational — governance verdict (approved/blocked) is what gates publishing.

## Issue-Driven Workflow

- Work is defined and tracked through GitHub issues.
- Each implementation PR should stay scoped to one issue.
- A PR branch should contain only the commits and file changes needed for that issue.
- Unrelated fixes, refactors, or follow-on improvements belong in separate issues and separate PRs.

## Side Issues

When a repair discovers issues unrelated to the primary issue being worked, the repair agent recommends opening separate issues. Structured as a `side_issues` field on `RepairResult`. These are included in the blocked run's publish plan as `follow_up_issue` actions.

## GitHub Transport

How the system reaches GitHub:

- `GITHUB_TRANSPORT=auto` — probe MCP first; fall back to `gh` CLI; error if neither available
- `GITHUB_TRANSPORT=mcp` — require MCP; error if unavailable
- `GITHUB_TRANSPORT=cli` — require `gh` CLI; error if unavailable

MCP availability is probed once per run and cached.

Token resolution: `GITHUB_TOKEN` (project) takes precedence over `OpenCode_Github_Token` (system-managed).

## Repair Agent

Single-shot code modifier. The LLM API (Vercel AI SDK or equivalent) is called directly — no `opencode` binary dependency. Agent makes one set of changes and stops. QA verifier runs separately. Governance decides when to stop.

Retry: manual via `repair issue --retry-from <run-id>`. Up to 3 attempts before `escalated` status.

## Docs Fix Prompt

`docs-fix-prompt.txt` is not a fix specification — it is a signal that side issues exist. When present for a non-docs-remediation issue, the repair agent is instructed to recommend surfacing them as separate issues. When present for a docs-remediation issue, the prompt content is the fix specification itself.

## Project Scope

Any project with a documented QA command — code or non-code (e.g., Unreal Engine blueprints). The system does not build test infrastructure; it executes whatever the project owner already documented. Language-agnostic at the architecture level.
