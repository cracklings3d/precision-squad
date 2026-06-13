---
issue: github.com/cracklings3d/precision-squad#184
title: Reconcile architecture.md stage chain with the 7-stage model
status: draft
plan_status: proposed
review_status: pending
source: issue
owner: cracklings3d
created_at: 2026-06-13
updated_at: 2026-06-13
approved_by: null
approved_at: null
review_artifact: null
related_branch: null
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/architecture.md
  directories: []
  modules: []
  artifacts: []
---

# Summary

Update the 6-stage numbered list in `docs/architecture.md:44-50` to reflect the canonical 7-stage chain by inserting the missing `review impl` stage and renaming `publish run` to `publish`, matching `docs/staged-command-surface.md:39-41` and ADR-008.

# Problem

`docs/architecture.md:44-50` (Execution Model section) lists an explicit 6-stage chain ending at `publish run` and omits `review impl`. The rest of `architecture.md` and `docs/staged-command-surface.md:39-41` use the 7-stage chain. A new contributor reading `architecture.md` first will see an inconsistent stage count and miss context when reading other documents.

# Acceptance Criteria

- [ ] `docs/architecture.md:44-50` lists all 7 stages in canonical order
- [ ] Stage named `publish run` is renamed to `publish`
- [ ] No other prose in `architecture.md` is changed

# In Scope

- Edit `docs/architecture.md:44-50` to replace the 6-stage list with a 7-stage list:
  - Insert `review impl` as stage 7
  - Rename `publish run` → `publish`

# Out Of Scope

- Reordering, merging, or renaming stages beyond the `publish run` → `publish` rename (separate ADR-008 issue)
- Editing `staged-command-surface.md` or any ADR
- Promoting any ADR from `Proposed` to `Accepted`

# Constraints

- No production code changes
- Only the numbered list at lines 44-50 may be modified

# Proposed Approach

1. Open `docs/architecture.md` and locate the 6-stage numbered list at lines 44-50
2. Replace `6. `publish run`` with `6. `publish``
3. Add new line `7. `review impl`` after line 49
4. Verify no other prose in the file is modified

# Impacted Areas

- `docs/architecture.md` (lines 44-50 only)

# Validation Plan

- Diff review confirms only lines 44-50 changed
- Numbered list shows exactly 7 stages in order: `create issue` → `review issue` → `plan` → `review plan` → `implement` → `publish` → `review impl`
- `publish run` does not appear anywhere in the modified file
- Other references to `review impl` elsewhere in architecture.md remain unchanged

# Risks

- None identified — docs-only change with explicit non-goals defined

# Open Questions

- None

# Approval Notes

- Prior review verdict: `pass` (run-20260613-231657)
- No blocking_findings or required_edits
- Issue is planner-ready
