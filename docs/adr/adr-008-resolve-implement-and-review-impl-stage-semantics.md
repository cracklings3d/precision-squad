# ADR-008: Resolve `implement` and `review impl` Stage Semantics

## Status

Accepted

## Date

2026-05-22

## Context

The workflow vocabulary around `implement`, `publish`, and `review impl` needs an explicit contract.

Without that contract, downstream work can drift into conflicting interpretations such as:

- treating `implement` as the stage that creates a branch or PR
- treating `review impl` as review of unpublished local workspace state
- collapsing `publish` into `implement`

Those interpretations would conflict with the already accepted governance rule in [VISION.md](../../VISION.md) and [ADR-001](./adr-001-governance-two-verdicts.md):

- `approved` means governance says yes
- `approved` creates `draft_pr` automatically
- that draft PR creation belongs to `publish`

Issue #66 is a decision-and-documentation slice only. It does not change CLI behavior, publish automation, or issue-state automation.

## Decision

Define the stage sequence as:

1. `implement`
2. `publish`
3. `review impl`

### `implement`

`implement` is the local, issue-scoped implementation stage.

It consumes:

- the approved issue-scoped planning or decision input for the run
- the local repository workspace for the single issue being executed

It produces:

- the local implementation diff for that issue
- persisted run artifacts needed for governance and later publish steps
- no PR and no branch as a direct stage output

### `publish`

`publish` is the boundary between local implementation and PR-based review.

It consumes:

- the stored implementation result from `implement`
- the governance verdict

It produces:

- a generated branch and draft PR when the verdict is `approved`
- persisted publish artifacts such as `publish-plan` and `publish-result`

`publish` occurs only after `implement` completes and governance returns `approved`.

### `review impl`

`review impl` is review of the published draft PR for the same issue.

It consumes:

- the published draft PR for the same issue, including URL or number and head SHA
- persisted run context needed to review that PR
- the PR diff and PR body, not an unpublished local-only implementation artifact

It produces:

- the post-publish implementation review result
- structured feedback back to the source issue when review rejects
- issue reopen or keep-open behavior on rejection
- no second PR and no broadened multi-issue output

### Timing Constraints

The workflow timing is locked down as follows:

- PR creation occurs during `publish`
- `publish` occurs after `implement` completes and after governance returns `approved`
- `review impl` occurs only after a draft PR already exists
- draft PR creation does not itself close the issue
- issue closure is outside the `implement` / `publish` / `review impl` contract for this slice

## Rationale

1. **Preserve accepted governance semantics.** This ADR keeps the accepted `approved -> draft_pr` rule intact instead of redefining governance.
2. **Keep stage responsibilities clear.** Local implementation, PR publication, and post-publish review are separate responsibilities with separate artifacts.
3. **Avoid local-only review ambiguity.** `review impl` should evaluate the published draft PR that other participants can inspect, not a transient unpublished workspace.
4. **Keep issue scope bounded.** This decision resolves terminology and artifact boundaries without expanding into execution changes.

## Consequences

- `implement` must be described as a local stage that does not directly create or update a PR.
- `publish` must be described as the step that creates the branch and draft PR after an `approved` governance verdict.
- `review impl` must be described as post-publish review of that draft PR.
- Documentation and future implementation work should treat persisted implementation artifacts and persisted publish artifacts as distinct handoff points.
- Issue closure remains governed elsewhere and is not implied by `implement`, `publish`, or draft PR creation.

## Verification

- [ ] `implement` stage does not call the GitHub transport to create a branch or PR
- [ ] `publish` stage is the only stage that produces `publish-plan.json` and `publish-result.json`
- [ ] `review impl` consumes the published draft PR (URL or number + head SHA), not an unpublished local-only workspace
- [ ] PR creation occurs after `governance-verdict.json` records `verdict: approved`

## References

- [VISION.md](../../VISION.md) — Governance Verdicts
- [ADR-001: Governance Two-Verdict Model](./adr-001-governance-two-verdicts.md)
- [architecture.md](../architecture.md) — Publishing And Review
- [staged-command-surface.md](../staged-command-surface.md) — Stage chain overview, `implement` / `publish` / `review impl` stage contract, and Artifact Inventory