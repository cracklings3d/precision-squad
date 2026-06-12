# Governance

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
