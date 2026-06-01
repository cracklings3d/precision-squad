---
issue: github.com/cracklings3d/precision-squad#149
title: Standardize review and governance artifact naming on verdict
status: approved
plan_status: approved
review_status: approved
source: issue
owner: cracklings3d
created_at: 2026-06-01
updated_at: 2026-06-01
approved_by: "canonical-issue-resolver stage-D review"
approved_at: 2026-06-01T02:02:00Z
review_artifact: "C:/Users/The_u/.opencode/projects/github-com-cracklings3d-precision-squad/runs/canonical-issue-resolver-parallel/cirp-20260601-020131-8bi7ja/reviews/issue-149/loop-2-stage-D.json"
related_branch: issue/149
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/issue-plans/issue-149.md
    - docs/staged-command-surface.md
    - src/precision_squad/models.py
    - src/precision_squad/run_store.py
    - src/precision_squad/coordinator.py
    - src/precision_squad/cli.py
    - src/precision_squad/governance.py
    - src/precision_squad/publishing.py
    - src/precision_squad/post_publish_review.py
    - tests/test_run_store.py
    - tests/test_governance.py
    - tests/test_publishing.py
    - tests/test_retry.py
    - tests/test_coordinator.py
    - tests/test_cli.py
    - tests/test_post_publish_review.py
    - tests/integration/test_stage_artifacts.py
    - tests/integration/test_pipeline_gate_chain.py
    - tests/integration/test_pipeline_blocked.py
    - tests/integration/support.py
  directories: []
  modules:
    - precision_squad.models
    - precision_squad.run_store
    - precision_squad.coordinator
    - precision_squad.cli
    - precision_squad.governance
    - precision_squad.publishing
    - precision_squad.post_publish_review
  artifacts:
    - issue-review.json
    - plan-review.json
    - impl-review.json
    - governance-verdict.json
---

# Summary

Issue #149 aligns canonical review and governance contracts on the single term `verdict`. The intended outcome is a narrow terminology and schema normalization across models, persistence/loaders, CLI/reporting, focused docs, and tests, while treating previously persisted legacy `review_status`/`status` artifacts as backward-compatible read inputs rather than a separate migration project.

# Problem

Current review artifacts use `review_status`, governance artifacts use `status`, and active artifact documentation already refers to `verdict`. That mismatch creates avoidable translation between code, persisted JSON, loaders, CLI/reporting, and docs, and it blocks dependent documentation issues that need one settled review/governance contract.

# Acceptance Criteria

- Canonical review artifacts (`issue-review.json`, `plan-review.json`, and `impl-review.json`) use `verdict` with values `approved`, `changes_requested`, or `blocked` in both models and persisted JSON.
- Canonical governance artifacts (`governance-verdict.json`) use `verdict` with values `approved` or `blocked` in both models and persisted JSON.
- Loader, validation, and retry/resume paths accept previously persisted legacy `review_status` / `status` keys only as backward-compatible inputs, normalize them to canonical `verdict`, and do not emit new legacy-key artifacts.
- Loaders, validation, gating logic, CLI/reporting, and related publish/review reporting surfaces agree on the same canonical field name and value sets end-to-end.
- Focused active docs that define artifact schema describe the same `verdict` terminology, including review-stage `changes_requested` where applicable, without broad operator/workflow rewrites.
- Unit and integration tests assert the unified review/governance terminology end-to-end.
- `docs/issue-plans/issue-149.md` exists in-repo as the canonical tracked plan artifact for this issue, and implementation review does not pass until actual stage-D approval metadata has been recorded on that tracked plan artifact.

# In Scope

- Rename canonical review/governance model fields and persisted JSON keys from `review_status`/`status` to `verdict` for issue review, plan review, implementation review, and governance verdict artifacts.
- Update persistence, loaders, validators, and gate checks so the renamed `verdict` contract is used consistently.
- Add the minimum backward-compatible normalization needed for existing persisted legacy-key artifacts during loader, validation, and retry/resume flows, without introducing a bulk migration or broad historical artifact rewrite.
- Update CLI/reporting and related publish/review messaging that currently surfaces review status or governance status so operator-facing output matches `verdict` terminology.
- Update the narrow active doc surface required to describe the renamed artifact schema, centered on `docs/staged-command-surface.md`.
- Update focused unit and integration coverage for the renamed contract.
- Maintain `docs/issue-plans/issue-149.md` as governed in-repo scope and carry it through actual stage-D approval metadata before downstream implementation review passes.

# Out Of Scope

- Repair-agent surface cleanup from #145.
- GitHub transport strategy and `GITHUB_TRANSPORT` behavior work from #146.
- Stale OpenSWE metadata cleanup from #147.
- Broad workflow or operator-guide rewrites tracked by #151 and #152, including wholesale README, CONTEXT, CONTRIBUTING, or `docs/operator-skill.md` refresh work beyond the minimum artifact-schema terminology required here.
- File renames, stage reordering, artifact lifecycle redesign, or new workflow states beyond review `approved|changes_requested|blocked` and governance `approved|blocked`.
- Changing reviewer/architect raw agent status vocabulary except where strictly necessary to keep canonical impl-review persistence and operator reporting consistent.

# Constraints

- Keep #149 limited to terminology and contract normalization; do not expand into general workflow redesign.
- Preserve the existing semantics while renaming the canonical contract surface: review remains tri-state and governance remains two-state.
- Preserve ADR-001 / ADR-008 semantics by treating legacy `review_status` / `status` support as a compatibility shim at load/validation/retry boundaries only; canonical persisted artifacts and gate decisions remain `verdict`-based with governance constrained to `approved|blocked`.
- Treat `docs/staged-command-surface.md` as the only active doc update required by this issue unless another file is strictly necessary to keep the renamed canonical artifact schema self-consistent.
- Keep #149 distinct from later dependent issues: #151 and #152 wait on this contract normalization but are not authorized by it.
- The in-repo plan artifact `docs/issue-plans/issue-149.md` is itself governed scope and must receive non-placeholder stage-D approval metadata before implementation review can pass.

# Proposed Approach

1. Update the canonical review/governance dataclasses and construction paths so `verdict` is the authoritative field name for issue review, plan review, implementation review, and governance verdict artifacts.
2. Update run-store serialization, JSON validation/loaders, gate checks, and coordinator/CLI/reporting code so all canonical persisted and operator-facing review/governance surfaces use `verdict` consistently, while legacy persisted `review_status` / `status` inputs are accepted only long enough to normalize them into the canonical in-memory and re-persisted shape during loader, validation, and retry/resume flows.
3. Update the narrow active artifact-schema documentation surface in `docs/staged-command-surface.md` so it matches the renamed fields and the current review/governance value sets, while leaving broader staged-workflow and operator-guide cleanup to #151 and #152.
4. Update focused unit and integration tests covering artifact persistence/loading, retry/resume, stage gating, publishing/reporting, and implementation review mapping so they assert the unified terminology end-to-end.
5. Before implementation review is treated as passing, revise this tracked plan artifact with actual stage-D approval metadata so the in-repo plan remains a governable prerequisite rather than a placeholder.

# Impacted Areas

- `src/precision_squad/models.py`
- `src/precision_squad/run_store.py`
- `src/precision_squad/coordinator.py`
- `src/precision_squad/cli.py`
- `src/precision_squad/governance.py`
- `src/precision_squad/publishing.py`
- `src/precision_squad/post_publish_review.py` (canonical impl-review/reporting surface only)
- `docs/staged-command-surface.md`
- Focused contract tests under `tests/` and `tests/integration/` named in `change_scope.files`
- `docs/issue-plans/issue-149.md`

# Validation Plan

- Verify `issue-review.json`, `plan-review.json`, and `impl-review.json` persist `verdict` and reject invalid values outside the review tri-state contract.
- Verify `governance-verdict.json` persists `verdict` and rejects invalid values outside `approved|blocked`.
- Verify previously persisted artifacts using legacy `review_status` / `status` keys still load for validation and retry/resume, normalize to `verdict`, and do not reintroduce legacy keys when re-persisted.
- Verify planning, implementation, publish gating, and CLI/reporting consume and display `verdict` consistently end-to-end.
- Verify the focused active doc surface describes the same field names and value sets as the code and persisted artifacts.
- Verify targeted unit and integration tests pass for artifact persistence/loading, retry/resume, stage gating, publishing/reporting, and implementation review mapping.
- Verify `docs/issue-plans/issue-149.md` remains in-repo and is updated with actual stage-D approval metadata before implementation review is treated as passing.

# Risks

- Renaming persisted fields can break loader, gate, or retry/resume paths if code and tests are updated inconsistently; mitigate by updating models, persistence, and end-to-end tests together.
- Documentation drift could pull this issue into the broader refresh tracked by #151 and #152; mitigate by limiting doc edits to the artifact-schema terminology required for the renamed contract.
- Touching canonical impl-review/reporting surfaces could accidentally spill into reviewer/architect sub-agent semantics; mitigate by keeping the change centered on persisted stage artifacts and operator-facing output only.

# Open Questions

- None currently. Broader active-doc and operator-guide cleanup remains intentionally deferred to #151 and #152 once #149 lands.

# Approval Notes

This plan is intentionally narrow within umbrella issue #144. It standardizes the canonical review/governance contract on `verdict`, remains distinct from #145, #146, and #147, and establishes the terminology floor that later doc issues #151 and #152 depend on. Because this tracked plan artifact is itself part of governed scope, `docs/issue-plans/issue-149.md` must remain in-repo and receive actual stage-D approval metadata (`approved_by`, `approved_at`, `review_artifact`, and corresponding approved frontmatter status fields) before implementation review for #149 may pass.
