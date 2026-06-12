# Workflow

Terms resolved through grill-with-docs session.

## Issue-Driven Workflow

- Work is defined and tracked through GitHub issues.
- Each implementation PR should stay scoped to one issue.
- A PR branch should contain only the commits and file changes needed for that issue.
- Unrelated fixes, refactors, or follow-on improvements belong in separate issues and separate PRs.

## Side Issues

When a repair discovers issues unrelated to the primary issue being worked, the repair agent recommends opening separate issues. Structured as a `side_issues` field on `RepairResult`. These are included in the blocked run's publish plan as `follow_up_issue` actions.
