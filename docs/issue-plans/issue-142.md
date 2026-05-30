---
issue: github.com/cracklings3d/precision-squad#142
title: Track docs/issue-plans/TEMPLATE.md in repository
status: draft
plan_status: proposed
review_status: pending
source: issue
owner: cracklings3d
created_at: 2026-05-30
updated_at: 2026-05-30
approved_by: null
approved_at: null
review_artifact: null
related_branch: issue/142
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/issue-plans/TEMPLATE.md
    - docs/issue-plans/issue-142.md
  directories: []
  modules: []
  artifacts: []
---

# Summary

Issue #142 exists to make the canonical issue-plan template a tracked repository file at `docs/issue-plans/TEMPLATE.md`. The intended outcome remains narrowly limited to adding that file with the verified template content pinned verbatim in this plan's Appendix A, so implementation and review can validate exact parity without redesigning the surrounding workflow.

# Problem

The repository's intended canonical plan template structure currently exists locally but is not tracked in the repository and is absent from `origin/master`. That gap leaves the canonical template path ungoverned in version control even though downstream issue plans are expected to follow that structure, and the prior plan revision did not pin an exact reviewable source artifact for the template content to be copied.

# Acceptance Criteria

- The repository tracks `docs/issue-plans/TEMPLATE.md` at that exact path.
- The tracked `docs/issue-plans/TEMPLATE.md` content matches the exact pinned template content embedded verbatim in Appendix A of `docs/issue-plans/issue-142.md`.
- `docs/issue-plans/issue-142.md` exists as the canonical tracked plan artifact governing this issue's narrow change.
- The change remains limited to tracking the template file and this issue plan artifact, with no broader workflow, process, or template-behavior changes.

# In Scope

- Add `docs/issue-plans/TEMPLATE.md` to the repository using the exact pinned template content embedded in Appendix A of this plan.
- Create and maintain `docs/issue-plans/issue-142.md` as the canonical governing plan for this issue.

# Out Of Scope

- Broader workflow, process, or behavior changes.
- Template redesign, template schema expansion, or template content changes beyond copying the current intended local structure into the tracked repository path.
- Any implementation work outside `docs/issue-plans/TEMPLATE.md` and this plan artifact.

# Constraints

- Keep scope extremely narrow and docs-focused.
- Treat Appendix A of this plan as the immutable reviewable source-of-truth artifact for the `docs/issue-plans/TEMPLATE.md` content in this issue.
- Local provenance may be referenced during review, but implementation must remain fully governable from this plan artifact in isolation.
- Do not redesign the canonical planning workflow or reinterpret the template while adding the tracked file.
- Do not implement unrelated repository or documentation changes alongside this issue.

# Proposed Approach

Revise `docs/issue-plans/issue-142.md` first so the plan itself contains the pinned source artifact needed to govern downstream work. Place the exact intended `docs/issue-plans/TEMPLATE.md` body in Appendix A and treat that appendix as the only implementation source for the template file content. Then, in the implementation stage, create `docs/issue-plans/TEMPLATE.md` by copying Appendix A verbatim into that path without editing, expanding, or reformatting the template structure. Keep the implementation and review surface bounded to `docs/issue-plans/TEMPLATE.md` and this plan artifact only.

# Impacted Areas

- `docs/issue-plans/TEMPLATE.md`
- `docs/issue-plans/issue-142.md`

# Validation Plan

- Verify `docs/issue-plans/issue-142.md` exists and governs only the narrow scope described in this issue.
- Verify Appendix A of `docs/issue-plans/issue-142.md` contains the complete pinned template content for `docs/issue-plans/TEMPLATE.md`.
- Verify `docs/issue-plans/TEMPLATE.md` is added as a tracked repository file at that exact path.
- Compare `docs/issue-plans/TEMPLATE.md` directly against Appendix A and confirm the file content is copied verbatim without reinterpretation.
- Verify no broader workflow, process, behavior, or template-redesign edits are included.

# Risks

- A supposedly small docs change could drift into template redesign or workflow changes; mitigate by limiting the change scope to the two named files and treating Appendix A as fixed input.
- The tracked file could differ from the intended template content; mitigate by explicitly comparing the tracked file content to Appendix A during validation.

# Open Questions

- None.

# Approval Notes

This plan is intentionally narrow. It governs only the addition of the tracked repository file `docs/issue-plans/TEMPLATE.md` using the exact content pinned in Appendix A below, plus this canonical issue-plan artifact at `docs/issue-plans/issue-142.md`.

# Appendix A - Pinned TEMPLATE.md Content

```md
---
issue: github.com/<owner>/<repo>#<number>
title: <short issue title>
status: draft
plan_status: proposed
review_status: pending
source: issue
owner: <owner or team>
created_at: YYYY-MM-DD
updated_at: YYYY-MM-DD
approved_by: null
approved_at: null
review_artifact: null
related_branch: null
related_pr: null
replaces: null
supersedes: null
change_scope:
  files: []
  directories: []
  modules: []
  artifacts: []
---

# Summary

State the problem and the intended outcome in 2-4 sentences.

# Problem

Describe the current behavior, gap, or risk this issue addresses.

# Acceptance Criteria

- <observable outcome>
- <observable outcome>

# In Scope

- <planned change>

# Out Of Scope

- <explicit non-goal>

# Constraints

- <technical, product, or process constraint>

# Proposed Approach

Describe the intended approach, major steps, and any important tradeoffs.

# Impacted Areas

- `<path, component, service, or artifact>`

# Validation Plan

- `<test, manual check, or verification step>`

# Risks

- <risk and mitigation>

# Open Questions

- <question or unresolved decision>

# Approval Notes

Record the decision summary, review outcome, or governing review link.
```
