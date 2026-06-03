---
issue: github.com/cracklings3d/precision-squad#147
title: Remove stale OpenSWE-era product metadata and active references
status: approved
plan_status: approved
review_status: approved
source: issue
owner: cracklings3d
created_at: 2026-06-01
updated_at: 2026-06-01
approved_by: "canonical-issue-resolver stage-D review"
approved_at: 2026-06-01T02:02:00Z
review_artifact: "C:/Users/The_u/.opencode/projects/github-com-cracklings3d-precision-squad/runs/canonical-issue-resolver-parallel/cirp-20260601-020131-8bi7ja/reviews/issue-147/loop-1-stage-D.json"
related_branch: issue/147
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - pyproject.toml
    - README.md
    - docs/architecture.md
    - docs/issue-plans/issue-147.md
  directories: []
  modules: []
  artifacts:
    - docs/issue-plans/issue-147.md
---

# Summary

Issue #147 removes stale OpenSWE-era product positioning from active metadata and any still-active product-facing documentation. The intended outcome is that current metadata and current docs describe `precision-squad` using its current docs-first, tool-backed identity while clearly archival or superseded historical references remain untouched.

# Problem

`pyproject.toml` still describes `precision-squad` as OpenSWE-backed, which conflicts with the repository's current product identity. Related active docs must be checked for the same stale positioning, but historical references in ADRs or archival materials are still acceptable when they are clearly presented as historical rather than current product truth.

# Acceptance Criteria

- `pyproject.toml` no longer describes the project as OpenSWE-backed and instead matches the current docs-first, tool-backed product identity already used in active docs.
- Active product-facing docs contain no stale OpenSWE-era positioning presented as current product truth.
- Clearly archival or superseded historical references remain in place unless they are actively presented as current product truth.
- `docs/issue-plans/issue-147.md` exists in the repository as the canonical governing plan artifact for this issue, and implementation review does not pass unless that in-repo artifact later carries real stage-D approval metadata.

# In Scope

- Update stale active product metadata in `pyproject.toml`.
- Audit and, only where necessary, remove stale OpenSWE-era positioning from the named active product-facing docs in this plan.
- Create and maintain `docs/issue-plans/issue-147.md` as the canonical tracked plan artifact for this issue.

# Out Of Scope

- General direct-LLM or OpenAI repair-surface cleanup covered by #145.
- GitHub transport runtime behavior or `GITHUB_TRANSPORT` semantics covered by #146.
- Review or governance verdict terminology normalization covered by #149.
- Removing or rewriting clearly archival references in `docs/archive/` or historical context in ADRs when they are explicitly presented as historical or superseded.
- Broader product rewording beyond removing stale OpenSWE-era current-state positioning.

# Constraints

- Keep #147 narrowly limited to stale OpenSWE-era active metadata and active references.
- Preserve archival and historical references unless they are actively presented as current product truth.
- Treat `docs/archive/` and `docs/adr/` as read-only historical context for this issue unless a reference there is surfaced as active current product truth.
- Do not use this issue to change repair-agent runtime support, dependency/runtime behavior, or verdict schemas.
- The canonical plan artifact must live in-repo at `docs/issue-plans/issue-147.md`; real stage-D approval metadata on that artifact is a prerequisite for a passing implementation review.

# Proposed Approach

First create this canonical tracked plan artifact so downstream work is governed in-repo. Then compare active metadata and active product-facing docs against the repository's current docs-first, tool-backed identity, updating only the places that still present OpenSWE as current positioning. During implementation, leave `docs/archive/*` and ADR historical language unchanged unless a specific reference is being surfaced as current product truth outside its archival context. Keep the edit set minimal and documentation-focused so the change does not drift into #145, #146, or #149.

# Impacted Areas

- `pyproject.toml`
- `README.md`
- `docs/architecture.md`
- `docs/issue-plans/issue-147.md`
- Historical-reference verification context only: `docs/archive/*`, `docs/adr/*`

# Validation Plan

- Verify `pyproject.toml` no longer contains OpenSWE-era product positioning and aligns with the repository's current docs-first, tool-backed identity.
- Verify active product-facing docs do not describe `precision-squad` as OpenSWE-backed or otherwise present OpenSWE-era positioning as current truth.
- Verify any remaining OpenSWE references are confined to clearly archival or historical contexts, or are explicitly marked as obsolete or superseded.
- Verify the implementation does not remove clearly archival references solely because they mention OpenSWE.
- Verify `docs/issue-plans/issue-147.md` exists in-repo and that implementation review remains blocked until real stage-D approval metadata is recorded on that artifact.

# Risks

- A docs cleanup could drift into broader repair-agent or architecture changes; mitigate by limiting edits to stale current-state positioning only.
- Historical references could be over-deleted; mitigate by preserving archival and ADR references unless they are presented as active truth.

# Open Questions

- None.

# Approval Notes

This plan governs only issue #147's narrow removal of stale OpenSWE-era current-state metadata and active references. It does not authorize broader cleanup of direct-LLM surfaces (#145), GitHub transport behavior (#146), or verdict terminology (#149), and it requires the in-repo canonical plan artifact to receive real stage-D approval metadata before implementation review can pass.
