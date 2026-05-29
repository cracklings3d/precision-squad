---
issue: github.com/cracklings3d/precision-squad#138
title: refactor: Decouple fresh-run gating from retry/resume restoration
status: approved
plan_status: approved
review_status: approved
source: issue
owner: cracklings3d
created_at: 2026-05-29
updated_at: 2026-05-29
approved_by: "canonical-issue-resolver stage-D review"
approved_at: 2026-05-29T17:56:00Z
review_artifact: 'C:\Users\The_u\.opencode\projects\github-com-cracklings3d-precision-squad\runs\canonical-issue-resolver-parallel\cirp-20260529T173000-template-recovery\reviews\issue-138\loop-1-stage-D.json'
related_branch: issue/138
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - src/precision_squad/coordinator.py
    - tests/integration/test_pipeline_gate_chain.py
    - tests/integration/test_retry_carry_forward.py
    - tests/integration/test_pipeline_blocked.py
    - src/precision_squad/run_store.py
    - tests/test_retry.py
    - tests/test_coordinator.py
  directories: []
  modules:
    - precision_squad.coordinator
    - precision_squad.run_store
  artifacts: []
---

# Summary

Issue #138 exists to separate fresh-run plan gating from retry/resume artifact restoration so coordinator behavior is easier to reason about and can unblock #116. The intended outcome is a narrow coordinator seam plus focused tests that keep fresh-run gating tied to current-run state while preserving retry-only restoration compatibility for prior approved plan artifacts.

# Problem

The current repair flow couples two different concerns: deciding whether a fresh run may proceed past the plan gate, and restoring prior-run artifacts during retry/resume handling. That coupling makes retry carry-forward behavior look like ordinary same-run approval semantics, which creates ambiguity in coordinator orchestration and in the tests that should distinguish fresh-run blocking from retry restoration.

# Acceptance Criteria

- Fresh runs still block at `review plan` when the current run has no approved plan artifact for the active attempt.
- Retry/resume restoration of a prior approved plan remains available only through an explicit retry-focused coordinator path, without expanding CLI or stage-resume behavior.
- Integration coverage clearly distinguishes fresh-run gate-chain behavior from retry carry-forward behavior.
- The change remains narrowly enabling for #116 and does not implement #116's broader stage-resume contract.

# In Scope

- Introduce or clarify a narrow coordinator seam in `src/precision_squad/coordinator.py` that separates fresh-run gate decisions from retry/restoration handling.
- Update focused integration coverage in `tests/integration/test_pipeline_gate_chain.py`, `tests/integration/test_retry_carry_forward.py`, and `tests/integration/test_pipeline_blocked.py` so fresh-run and retry expectations are asserted independently.
- Touch `src/precision_squad/run_store.py`, `tests/test_retry.py`, or `tests/test_coordinator.py` only if strictly necessary to support the coordinator seam or focused validation.

# Out Of Scope

- Implementing issue #116 or adding a `--from <stage>` stage-resume contract.
- Expanding CLI surface area, adding stages, or redesigning the broader staged workflow.
- Redesigning artifact schemas, publish/review governance, or retry/resume policy beyond the narrow coordinator boundary needed here.

# Constraints

- Keep the change surface centered on the coordinator seam and the named focused tests.
- Preserve current fresh-run gating behavior and current retry compatibility unless a targeted failing test proves an existing assumption wrong.
- Make retry/restoration behavior explicit and local rather than relying on shared implicit approval state.
- Do not drift into partial implementation of #116.

# Proposed Approach

Refactor coordinator orchestration so fresh-run plan gating and retry/restoration ingress are expressed as separate decisions instead of flowing through the same implicit path. Keep fresh-run gating dependent on current-run artifacts for the active attempt, while moving prior approved-plan reuse behind an explicit retry-only restoration branch. Then tighten the named integration tests so they prove the separation directly: fresh-run tests should assert blocking without a current-run approved plan, and retry tests should assert compatibility carry-forward without implying fresh-run auto-approval semantics.

# Impacted Areas

- `src/precision_squad/coordinator.py`
- `tests/integration/test_pipeline_gate_chain.py`
- `tests/integration/test_retry_carry_forward.py`
- `tests/integration/test_pipeline_blocked.py`
- `src/precision_squad/run_store.py` (spillover only if strictly necessary)
- `tests/test_retry.py` (spillover only if strictly necessary)
- `tests/test_coordinator.py` (spillover only if strictly necessary)

# Validation Plan

- Verify a fresh run without a current-run approved plan still stops at `review plan` and does not proceed into later stages.
- Verify retry from a prior run can still restore the approved plan through an explicit retry path while leaving prior-run artifacts unchanged.
- Verify the updated integration tests and any strictly necessary unit coverage use names and assertions that clearly separate fresh-run gating from retry restoration.
- Verify no new CLI behavior, stage-resume routing, or broader workflow redesign appears in the change.

# Risks

- A coordinator refactor could accidentally preserve the same hidden coupling under different names; mitigate by writing tests that prove fresh-run and retry paths independently.
- Small spillover into run-store or unit tests could widen scope; mitigate by allowing only strictly necessary supporting edits and keeping all other workflow surfaces unchanged.

# Open Questions

- None currently; the governing direction is to keep the surface narrow and enabling for #116 without adding new resume semantics.

# Approval Notes

This tracked plan translates the prior home-root draft into the repository's canonical `docs/issue-plans/issue-138.md` format. It governs only the narrow coordinator seam and focused validation needed for issue #138, with issue #116 explicitly treated as the blocked follow-on dependency rather than part of this implementation scope.

Formal approval was recorded by the canonical issue resolver stage-D pass at `C:\Users\The_u\.opencode\projects\github-com-cracklings3d-precision-squad\runs\canonical-issue-resolver-parallel\cirp-20260529T173000-template-recovery\reviews\issue-138\loop-1-stage-D.json` on `2026-05-29T17:56:00Z`.
