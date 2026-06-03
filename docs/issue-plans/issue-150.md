---
issue: github.com/cracklings3d/precision-squad#150
title: Remove obsolete generated project status reporting from the active docs set
status: draft
plan_status: proposed
review_status: pending
source: issue
owner: cracklings3d
created_at: 2026-06-03
updated_at: 2026-06-03
stage_c_pass_at: 2026-06-03
approved_by: null
approved_at: null
review_artifact: null
related_branch: issue/150-remove-project-status
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/project-status-report.md
    - docs/archive/project-status-report.md
    - docs/implementation-plan.md
    - docs/issue-plans/issue-147.md
    - docs/issue-plans/issue-150.md
  directories: []
  modules: []
  artifacts: []
---

# Summary

Issue #150 retires `docs/project-status-report.md` from the active docs set because it is a generated, dated snapshot that is no longer an ADR-backed source of truth. The intended outcome is that no active planning or overview doc treats the status report as authoritative, and any retained copy is clearly labeled as archival snapshot material.

# Problem

`docs/project-status-report.md` is a manually authored point-in-time snapshot (dated 2026-04-30) describing repository state at version 0.1.0. It is not grounded in any ADR, drifts the moment any module changes, and currently sits in the active docs set where a reader could mistake it for current product truth. Two active sections of `docs/implementation-plan.md` (1.8 and 6.5) still instruct future work to update this report, which would re-entrench the staleness rather than resolve it. The umbrella reconciliation issue #144 has already identified that "non-authoritative generated status reporting" should not remain in the active docs set.

# Acceptance Criteria

- `docs/project-status-report.md` is no longer in the active docs set; it is either deleted or moved into `docs/archive/` with a clear archival banner that marks it as a historical snapshot.
- `docs/implementation-plan.md` no longer contains active instructions that reference `docs/project-status-report.md` (sections 1.8 and 6.5 are removed or rewritten so they do not direct future work at a removed file).
- No remaining active planning or overview doc (`docs/staged-command-surface.md`, `docs/operator-skill.md`, `docs/architecture.md`, `docs/implementation-plan.md`, and the canonical tracked issue plans under `docs/issue-plans/`) treats the project status report as a current source of truth.
- If a copy is retained in `docs/archive/`, it is preceded by a short archival banner that states the snapshot date, the repository state it described, and the fact that it is not authoritative.
- `docs/issue-plans/issue-150.md` exists in-repo as the canonical tracked plan artifact for this issue, and implementation review does not pass until real stage-D approval metadata has been recorded on that tracked plan artifact.

# In Scope

- Remove `docs/project-status-report.md` from the active docs set, either by deletion or by moving the file to `docs/archive/project-status-report.md` with an archival banner.
- Remove or rewrite the two active references to `docs/project-status-report.md` in `docs/implementation-plan.md` (the `### 1.8` and `### 6.5` sub-sections) so that future work is not directed at a removed file.
- Audit the remaining active docs and tracked issue plans for any further active references to the project status report and remove or rewrite each occurrence.
- Update the bookkeeping entries in the already-approved `docs/issue-plans/issue-147.md` so its `change_scope.files` list and Impacted Areas no longer claim `docs/project-status-report.md` as in-scope work; this is a reference-list correction only and does not alter the approved scope, acceptance criteria, or approval metadata of #147.
- Maintain `docs/issue-plans/issue-150.md` as the canonical in-repo tracked plan artifact for this issue.

# Out Of Scope

- Broad active-doc refresh work tracked by other sub-issues of #144, including the wholesale `docs/architecture.md`, `docs/operator-skill.md`, or `docs/staged-command-surface.md` rewrites.
- Any change to the source code in `src/precision_squad/` or to test files under `tests/`; the status report is a docs-only artifact and code is not implicated.
- Replacement tooling or automation that would regenerate a status report in the future; the issue is strictly about removing the existing artifact from the active docs set.
- Renaming, restructuring, or deprecating the `docs/archive/` directory or its existing contents (`PRECISION_SQUAD_HANDOFF.md`, `architecture-v1.md`); archival placement of the status report is purely additive.
- Rewriting or re-approving the plan for #147; the reference-list correction is bookkeeping only and must not be framed as a scope change to #147.

# Constraints

- Keep #150 strictly limited to the active-doc removal/archival of one file plus the cleanup of its active references; do not expand into broader docs or code changes covered by sibling sub-issues of #144.
- Preserve any historical or operator-useful content from the status report when moving it to `docs/archive/`; the archival copy is permitted to be the file's existing contents prefixed with a short archival banner.
- Treat `docs/archive/` as the only permissible archival location for this issue; do not invent a new archival directory or move the file outside the repository.
- The `docs/implementation-plan.md` edits must remove the two referencing sub-sections rather than redirect them at another file; redirection would re-introduce active dependence on the status report.
- The `docs/issue-plans/issue-147.md` edit is a reference-list correction only; it must not modify #147's acceptance criteria, constraints, or approval metadata, and must not be presented as a new revision of #147.
- The canonical plan artifact must live in-repo at `docs/issue-plans/issue-150.md`; real stage-D approval metadata on that artifact is a prerequisite for a passing implementation review.
- Do not modify the umbrella issue #144 or any other open/approved sub-issue's issue body; this plan is contained to its own tracked artifact and the files listed in `change_scope.files`.

# Proposed Approach

First create this canonical tracked plan artifact so downstream work is governed in-repo. Then choose archival as the disposal path (over deletion) because the status report contains dated historical content that may still be useful as a snapshot, and the existing `docs/archive/` directory is already a known landing zone for such material; the acceptance criteria permit either deletion or archival, so archival is selected as the lower-risk option. Move `docs/project-status-report.md` to `docs/archive/project-status-report.md` and prepend a short archival banner that records the snapshot date, the repository state it described, and a clear statement that the file is not authoritative. Then remove the two active instructions in `docs/implementation-plan.md` (the `### 1.8` and `### 6.5` sub-sections) without redirecting them elsewhere, and audit the remaining active docs and tracked issue plans for any additional active references. Finally, correct the bookkeeping entries in `docs/issue-plans/issue-147.md` so its `change_scope.files` list and Impacted Areas no longer name the project status report, leaving the rest of #147's approved plan untouched. After all edits, sweep the active docs and tracked issue plans one more time to confirm no active source of truth still names the status report.

# Impacted Areas

- `docs/project-status-report.md` (moved out of the active docs set)
- `docs/archive/project-status-report.md` (archival destination, if archival is chosen)
- `docs/implementation-plan.md` (sections `### 1.8` and `### 6.5` removed)
- `docs/issue-plans/issue-147.md` (bookkeeping-only reference-list correction; no scope, criteria, or approval-metadata change)
- `docs/issue-plans/issue-150.md` (this canonical tracked plan artifact)
- Audit-only context: `docs/staged-command-surface.md`, `docs/operator-skill.md`, `docs/architecture.md`, other tracked issue plans under `docs/issue-plans/`

# Validation Plan

- Verify `docs/project-status-report.md` is no longer present at its original path in the active docs set.
- Verify, if archival was chosen, that `docs/archive/project-status-report.md` exists and begins with an archival banner that clearly states the snapshot date, the repository state it described, and that the file is not authoritative.
- Verify `docs/implementation-plan.md` contains no active instructions that name `docs/project-status-report.md` (the `### 1.8` and `### 6.5` sub-sections are gone and not redirected elsewhere).
- Verify a repository-wide content search for `project-status-report`, `Project Status Report`, and `project status report` returns no matches in the active docs set (`docs/*.md` excluding `docs/archive/` and `docs/issue-plans/issue-147.md`/`issue-150.md`), and that any remaining matches are confined to `docs/archive/`, `docs/issue-plans/issue-147.md` (bookkeeping correction only, scoped to the reference-list update), or `docs/issue-plans/issue-150.md` (this plan).
- Verify `docs/issue-plans/issue-147.md` is otherwise unchanged: its issue identifier, acceptance criteria, constraints, approval metadata (`approved_by`, `approved_at`, `review_artifact`), and `plan_status` / `review_status` values are not modified by this work.
- Verify `docs/issue-plans/issue-150.md` exists in-repo, carries the canonical frontmatter from the template, and that implementation review does not pass until fresh stage-D approval metadata has been recorded on that artifact.

# Risks

- An implementation that deletes the file outright (rather than archiving) loses historical reference value; mitigate by selecting archival as the default disposal path and documenting it in the Proposed Approach.
- Cleanup of `docs/implementation-plan.md` could drift into broader rewrites of the implementation plan; mitigate by strictly removing the two named sub-sections and leaving the rest of the plan untouched.
- Editing `docs/issue-plans/issue-147.md` could be read as scope drift on an already-approved plan; mitigate by framing the edit as a reference-list correction only, leaving the approved scope, criteria, and approval metadata of #147 intact, and calling this constraint out explicitly in the Constraints section.
- A reader could still encounter an old link or cached copy of the status report; mitigate by ensuring the archival banner is unambiguous and the file's new location is the only remaining repository path that returns the original content.

# Open Questions

- None at planning time. If archival reveals that the snapshot's contents are misleading even as historical material, the implementation may delete the file instead; this is permitted by the acceptance criteria and does not require a plan revision.

# Approval Notes

This plan governs only the removal/archival of `docs/project-status-report.md` from the active docs set and the cleanup of its active references. It does not authorize broader active-doc rewrites covered by sibling sub-issues of #144, any source code or test changes, or a scope revision of the already-approved plan for #147. The canonical plan artifact must receive real stage-D approval metadata before implementation review for #150 may pass.

## Stage C Transition (2026-06-03)

Plan reviewed against the template at `docs/issue-plans/TEMPLATE.md` for transition to Stage D plan review. All required YAML frontmatter fields and required sections are present and conform to the template. Frontmatter is intentionally in the `proposed` / `pending` state — approval metadata (`approved_by`, `approved_at`, `review_artifact`) is `null` and must remain `null` until Stage D plan review records a pass verdict. The `related_branch` field references `issue/150-remove-project-status` (the local implementation branch); it will be promoted to the remote and `related_pr` populated during the stage-D/stage-E workflow after this plan is approved. Scope, acceptance criteria, and constraints are unchanged from the original draft.
