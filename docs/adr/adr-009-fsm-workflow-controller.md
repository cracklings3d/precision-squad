# ADR-009: FSM Workflow Controller Architecture

## Status

Proposed

## Date

2026-06-03

## Context

The seven-stage workflow (`create issue` -> `review issue` -> `plan` -> `review plan` -> `implement` -> `publish` -> `review impl`) is currently orchestrated implicitly. That implicit orchestration is correct in many places but is not inspectable, is not exercisable as a state model, and conflates "which subagent produced the artifact" with "which transition fired."

Per the [staged-command-surface](./staged-command-surface.md), each stage is owned by a designated per-stage subagent:

| Stage | Designated subagent | Produced artifact |
|-------|---------------------|------------------|
| `create issue` | Issue Intake subagent | `issue-draft.json` |
| `review issue` | Issue Reviewer | `issue-review.json` |
| `plan` | Architect | `approved-plan.json` |
| `review plan` | Plan Reviewer | `plan-review.json` |
| `implement` | Developer | `execution-result.json`, `governance-verdict.json` |
| `publish` | Merge Coordinator | `publish-plan.json`, `publish-result.json` |
| `review impl` | Reviewer | `impl-review.json` |

Each stage carries a gate verdict (`approved` | `changes_requested` | `blocked`) that controls whether the controller advances to the next stage. The controller's decision to advance is implicit: it is derived from the presence or absence of an `approved` artifact rather than being an explicit, named transition. Downstream consumers of persisted run state cannot answer "what stage is run X in and why?" without re-deriving the chain from logs.

Per [architecture.md](../architecture.md), run state is filesystem-backed and transparent. The persistence model stores artifacts for each stage but does not store an explicit run state label. The [repair issue --retry-from contract](../staged-command-surface.md#repair-issue-manual-retry-resume-contract) supports resuming from `review issue`, `plan`, `review plan`, `implement`, `publish`, and `review impl`, with a resume matrix that tracks which artifacts are preserved and regenerated per resume target.

This ADR evaluates whether an explicit FSM controller—modeling the seven stages as named states and the gate verdicts as named events—would improve the workflow on six falsifiable axes.

## Decision

Outcome: **Go - documentation-only migration slice**. The FSM model is valuable as documentation for inspectability and testability, and a documentation-only slice produces that value without the migration cost of a live controller. The FSM model and this ADR are the only output; no production code, no run-store schema changes, no changes to existing ADRs, and no changes to [staged-command-surface.md](./staged-command-surface.md) or [architecture.md](../architecture.md) are authorized by this slice.

### Proposed FSM State Set

The FSM models seven operational states (one per completed stage) plus four terminal states:

| State | Meaning |
|-------|---------|
| `CREATED` | `create issue` completed; `issue-draft.json` is present |
| `REVIEWED` | `review issue` returned `approved`; `issue-review.json` is present with `verdict: approved` |
| `PLANNED` | `plan` returned `approved`; `approved-plan.json` is present |
| `PLAN_REVIEWED` | `review plan` returned `approved`; `plan-review.json` is present with `verdict: approved` |
| `IMPLEMENTED` | `implement` completed with `governance-verdict: approved`; `governance-verdict.json` is present |
| `PUBLISHED` | `publish` created draft PR; `publish-result.json` is present with PR metadata |
| `IMPL_REVIEWED` | `review impl` returned `approved`; `impl-review.json` is present with `verdict: approved` |
| `BLOCKED` | Terminal; a stage returned a non-advance verdict |
| `CHANGES_REQUESTED` | Terminal; `review impl` or `review issue` returned `changes_requested` |
| `ABANDONED` | Terminal; run was explicitly abandoned or timed out |

### Event Alphabet

| Event | Triggering condition |
|-------|----------------------|
| `review_approved` | `issue-review.json` contains `verdict: approved` |
| `review_blocked` | `issue-review.json` contains `verdict: blocked` |
| `review_changes_requested` | `issue-review.json` contains `verdict: changes_requested` |
| `plan_approved` | `approved-plan.json` is produced |
| `plan_blocked` | `plan` stage produced no `approved-plan.json` |
| `plan_review_approved` | `plan-review.json` contains `verdict: approved` |
| `plan_review_blocked` | `plan-review.json` contains `verdict: blocked` |
| `plan_review_changes_requested` | `plan-review.json` contains `verdict: changes_requested` |
| `governance_approved` | `governance-verdict.json` contains `verdict: approved` |
| `governance_blocked` | `governance-verdict.json` contains `verdict: blocked` |
| `publish_ready` | `publish` stage has all required inputs per the resume matrix |
| `impl_review_approved` | `impl-review.json` contains `verdict: approved` |
| `impl_review_blocked` | `impl-review.json` contains `verdict: blocked` |
| `impl_review_changes_requested` | `impl-review.json` contains `verdict: changes_requested` |
| `repair_accepted` | Controller accepted a `repair issue --retry-from` command |
| `run_abandoned` | Run was explicitly marked abandoned |

### Transition Table

Every transition is named in `(state, event) -> state` form and mapped to either deterministic controller logic or a designated per-stage subagent:

| # | Current state | Event | Next state | Handler | Rationale |
|---|---------------|-------|------------|---------|-----------|
| 1 | `CREATED` | `review_approved` | `REVIEWED` | Controller logic | Deterministic: `issue-review.json` with `verdict: approved` is sufficient signal |
| 2 | `CREATED` | `review_blocked` | `BLOCKED` | Controller logic | Terminal; no advance |
| 3 | `CREATED` | `review_changes_requested` | `CHANGES_REQUESTED` | Controller logic | Terminal per governance vocabulary |
| 4 | `REVIEWED` | `plan_approved` | `PLANNED` | Architect subagent | Subagent produces `approved-plan.json` |
| 5 | `REVIEWED` | `plan_blocked` | `BLOCKED` | Architect subagent | Terminal; no artifact produced |
| 6 | `PLANNED` | `plan_review_approved` | `PLAN_REVIEWED` | Plan Reviewer subagent | Subagent produces `plan-review.json` with `verdict: approved` |
| 7 | `PLANNED` | `plan_review_blocked` | `BLOCKED` | Plan Reviewer subagent | Terminal; gate not met |
| 8 | `PLANNED` | `plan_review_changes_requested` | `CHANGES_REQUESTED` | Plan Reviewer subagent | Terminal per governance vocabulary |
| 9 | `PLAN_REVIEWED` | `governance_approved` | `IMPLEMENTED` | Governance logic (controller) | Deterministic: `governance-verdict.json` with `verdict: approved` |
| 10 | `PLAN_REVIEWED` | `governance_blocked` | `BLOCKED` | Governance logic (controller) | Terminal; publish is gated on `approved` |
| 11 | `IMPLEMENTED` | `publish_ready` | `PUBLISHED` | Merge Coordinator subagent | Subagent creates draft PR; this event fires after all implement artifacts are persisted |
| 12 | `PUBLISHED` | `impl_review_approved` | `IMPL_REVIEWED` | Reviewer subagent | Subagent produces `impl-review.json` with `verdict: approved` |
| 13 | `PUBLISHED` | `impl_review_blocked` | `BLOCKED` | Reviewer subagent | Terminal; issue reopen/keep-open handled by GitHub automation |
| 14 | `PUBLISHED` | `impl_review_changes_requested` | `CHANGES_REQUESTED` | Reviewer subagent | Terminal per governance vocabulary |
| 15 | `*` | `repair_accepted` | Resume target | Controller logic | Deterministic: resume target is derived from `--from` argument; run/attempt split is applied per resume matrix |

Transition #15 is the repair/resume path. It applies from any non-terminal state and targets the stage named by `--from`. The new attempt is a fresh run directory; prior run directories remain unchanged. This is the only transition that can fire from multiple source states and is handled entirely by controller logic.

The FSM preserves the stage boundaries defined by [ADR-008](./adr-008-resolve-implement-and-review-impl-stage-semantics.md): `implement` is local-only (no branch, no PR), `publish` is the boundary that creates a draft PR, and `review impl` reviews the published draft PR.

## Rationale

### Stage-transition testability

The FSM makes every transition nameable and exercisable in isolation. Under the current implicit model, "did the `implement` -> `publish` transition fire correctly?" requires running the full `implement` stage with an LLM-driven Developer subagent and then checking for a draft PR. Under the FSM model, the same question is answered with a fixed `governance-verdict.json` fixture (with `verdict: approved`) and a `publish_ready` event; the controller's transition function deterministically advances to `PUBLISHED` without an LLM. **This axis supports Go**: the FSM improves testability of the gate-driven transitions.

However, the subagent-owned transitions (Architect, Plan Reviewer, Developer, Merge Coordinator, Reviewer) still require their respective subagent invocations to produce their output artifacts. The FSM does not eliminate LLM involvement for those stages; it only makes the controller's role explicit. If the goal is full LLM-free transition testing, a subsequent code slice would need to provide deterministic subagent mocks or replay fixtures for each stage artifact.

### Retry and resume behavior

The FSM treats `repair_accepted` as a first-class event (transition #15) that can fire from any non-terminal state and advance to the designated resume target. This is compatible with the existing `repair issue --retry-from RUN_ID --from STAGE_NAME` contract in [staged-command-surface.md](./staged-command-surface.md), which supports resume from `review issue`, `plan`, `review plan`, `implement`, `publish`, and `review impl`. The run/attempt split is preserved: each `--retry-from` creates a new attempt directory with fresh `run-request.json`, copied `issue-intake.json`, and regenerated `issue.md`, while artifacts before the resume point are copied from the source run per the resume matrix. **This axis supports Go**: the FSM models retry as an explicit event without requiring changes to the resume contract or the run/attempt split.

### Gate-verdict clarity

The FSM event alphabet names the gate verdicts explicitly (`governance_approved`, `governance_blocked`, `plan_review_approved`, etc.). The controller's transition function maps each (state, event) pair to exactly one next state, making the gate semantics unambiguous. The governance rule from [CONTEXT.md](../../CONTEXT.md) (that `approved` gates `publish`) is preserved: transition #11 (`IMPLEMENTED` + `publish_ready` -> `PUBLISHED`) fires only after `governance_approved` (transition #9) has already fired. The tri-state vocabulary (`approved` | `changes_requested` | `blocked`) from [ADR-001](./adr-001-governance-two-verdicts.md) is preserved as terminal event labels. **This axis supports Go**: the FSM makes gate verdicts explicit and eliminates the current implicit derivation from artifact presence.

### Migration cost

The FSM state set, event alphabet, and transition table are documentation. The only output of this issue is this ADR. No changes to the run-store JSON schema, no new controller module, no changes to [staged-command-surface.md](./staged-command-surface.md) or [architecture.md](../architecture.md), and no changes to existing ADRs are required for this slice. A subsequent code-slice issue could implement the FSM model as a state-machine interpreter or transition-table loader, but that is deferred. **This axis supports Go (documentation-only)**: migration cost for this slice is zero. Migration cost for a subsequent code slice is unknown and must be estimated by a separate issue.

### Inspectability of run state

Under the current implicit model, "what stage is run X in?" requires scanning the run directory for the most-recently-produced artifact and inferring the current stage from the artifact inventory. Under the FSM model, the current state is an explicit label (one of the eleven states) stored alongside the run metadata. A reviewer or operator can answer the question by reading the state label without re-deriving from artifacts. **This axis supports Go**: the FSM improves inspectability. If implemented in a subsequent code slice, the run record would gain an explicit `fsm_state` field.

### Stage-boundary preservation

The FSM models the seven stages in their current order with their current boundaries. No transitions are added, removed, or reordered. The `implement` / `publish` / `review impl` boundaries from [ADR-008](./adr-008-resolve-implement-and-review-impl-stage-semantics.md) are constraints on the FSM design: the FSM must not permit `publish` to fire before `governance_approved`, and `review impl` must only consume the published draft PR. Transition #11 (`IMPLEMENTED` + `publish_ready` -> `PUBLISHED`) fires after `governance_approved` (transition #9), which enforces the `implement` -> `publish` ordering. **This axis supports Go**: the FSM preserves stage boundaries as constraints.

## Consequences

### For Go (documentation-only slice)

- This ADR (`docs/adr/adr-009-fsm-workflow-controller.md`) is produced.
- The [canonical tracked plan artifact](./issue-plans/issue-153.md) for this issue is updated to reflect completion.
- No production code under `src/precision_squad/` is created or modified.
- No test files are created or modified.
- No changes to [staged-command-surface.md](./staged-command-surface.md), [architecture.md](../architecture.md), [CONTEXT.md](../../CONTEXT.md), or any existing ADR.
- The FSM model in this ADR becomes the reference design for any future code-slice implementation.

### Future code-slice envelope (out of scope for this slice)

If a subsequent issue implements the FSM controller in code, it must and must not:
- **Must**: implement the FSM as a state-machine interpreter that reads the transition table and advances the run state deterministically.
- **Must**: preserve the `repair issue --retry-from` contract and the run/attempt split.
- **Must not**: change the seven-stage order, merge stages, split stages, or rename stages.
- **Must not**: change the `implement` / `publish` / `review impl` boundaries from [ADR-008](./adr-008-resolve-implement-and-review-impl-stage-semantics.md).
- **Must not**: change the governance vocabulary (`approved` | `blocked`) or the review vocabulary (`approved` | `changes_requested` | `blocked`).

### For No-go (keep implicit orchestration)

If this ADR were to recommend No-go, the dominant reason would be: the current implicit orchestration is functional and low-risk, and the FSM model's inspectability and testability benefits do not justify the code-slice implementation cost unless a concrete use case (e.g., deterministic transition test fixtures) demands it. The smallest useful follow-up would be to add an informal state-diagram section to [architecture.md](../architecture.md) so the implicit model is at least documented visually.

## References

- [CONTEXT.md](../../CONTEXT.md) — Governance verdicts, `approved` gates `publish`
- [architecture.md](../architecture.md) — Persistence model, run state, stage chain
- [staged-command-surface.md](./staged-command-surface.md) — Seven-stage chain, per-stage subagents, resume matrix, repair contract
- [ADR-001: Governance Two-Verdict Model](./adr-001-governance-two-verdicts.md) — Two-state governance vocabulary
- [ADR-002: LLM Abstraction](./adr-002-llm-abstraction.md) — Per-stage subagent designation
- [ADR-005: Tool-Backed Repair Agent Adapters](./adr-005-tool-backed-repair-agent-adapters.md) — Repair agent architecture
- [ADR-008: Resolve Implement and Review Impl Stage Semantics](./adr-008-resolve-implement-and-review-impl-stage-semantics.md) — implement/publish/review impl boundaries
- [Canonical tracked plan for this issue](./issue-plans/issue-153.md)
