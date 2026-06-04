---
issue: github.com/cracklings3d/precision-squad#151
title: Refresh staged workflow documentation to match actual artifacts and review semantics
status: draft
plan_status: proposed
review_status: pending
source: issue
owner: cracklings3d
created_at: 2026-06-03
updated_at: 2026-04
approved_by: null
approved_at: null
review_artifact: null
related_branch: issue/151-refresh-staged-workflow-docs
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/issue-plans/issue-151.md
    - docs/staged-command-surface.md
    - README.md
    - docs/architecture.md
    - docs/adr/adr-001-governance-two-verdicts.md
    - docs/adr/adr-008-resolve-implement-and-review-impl-stage-semantics.md
  directories: []
  modules: []
  artifacts:
    - docs/issue-plans/issue-151.md
    - issue-review.json
    - plan-review.json
    - impl-review.json
    - governance-verdict.json
    - run-request.json
    - issue-intake.json
    - issue.md
---

# Summary

Issue #151 brings the active stage-oriented documentation back into agreement with the implemented staged workflow and the unified `verdict` artifact contract settled by #149. The intended outcome is that `docs/staged-command-surface.md`, the `README.md` "CLI" section, and the governance/artifact sections of `docs/architecture.md` describe the same stage chain, the same per-stage inputs/outputs, the same run-level vs stage-level artifact classification, and the same `verdict` field semantics, with ADR-001 and ADR-008 cross-referenced where they govern that contract.

# Problem

The active doc surface no longer matches the implemented workflow and the renamed artifact schema in three coordinated ways:

- `docs/staged-command-surface.md` already uses `verdict` and `changes_requested` in the review stage descriptions (lines 66, 95, 155) and already separates "stage-produced artifacts" (Artifact Inventory table at lines 162-180) from "Non-stage context artifacts" (the section heading at line 197 covering `run-request.json`, `issue-intake.json`, `issue.md`). However, the README's per-stage CLI stop descriptions (lines 219-247) and `docs/architecture.md`'s "Important Persisted Artifacts" section (lines 296-322) and governance section do not yet use the same artifact names or the same run-level vs stage-level classification.
- The original issue's terms ("stage artifacts", "run-provenance artifacts") do not match the vocabulary used in the staged-command-surface doc, so cross-doc references read as if they describe different artifact classes.
- `docs/architecture.md`'s "Important Persisted Artifacts" list and governance section still need to be confirmed against the current review/governance value sets (`verdict: approved | changes_requested | blocked` for review artifacts, `verdict: approved | blocked` for `governance-verdict.json`) settled by #149 and ADR-001.

Without that alignment, a reader has to translate between three different doc surfaces to know what the seven-stage chain actually produces, and reviewers/operators cannot rely on a single vocabulary for run-level vs stage-level artifacts.

# Acceptance Criteria

- `docs/staged-command-surface.md` reflects the actual stage chain and current artifact schema: the Artifact Inventory, per-stage Inputs/Outputs, gate behavior, and the "Non-stage context artifacts" sub-section under "Resume matrix" all match the implemented workflow.
- The "Non-stage context artifacts" terminology in `docs/staged-command-surface.md` is used consistently to describe run-level context artifacts (`run-request.json`, `issue-intake.json`, `issue.md`), distinct from the stage-produced artifacts listed in the Artifact Inventory, without implying the run-level artifacts do not exist; the "Non-stage context artifacts" sub-section is treated as the canonical run-level artifact inventory and is named explicitly in the doc's headings rather than being merged silently into the Artifact Inventory table.
- `README.md` "CLI" section per-stage stop descriptions (the `create issue`, `review issue`, `plan`, `review plan`, and `implement` bullets at lines 219-247, under the heading that introduces the staged `repair issue` command) use the same artifact names and the same run-level vs stage-level classification as `docs/staged-command-surface.md`; bullets for stages that produce run-level context artifacts (`create issue`) name the run-level artifacts separately from the stage-produced artifacts.
- `docs/architecture.md` governance section and "Important Persisted Artifacts" section use the current field names and semantics — `verdict` with `approved` | `changes_requested` | `blocked` for review artifacts (`issue-review.json`, `plan-review.json`, `impl-review.json`) and `verdict` with `approved` | `blocked` for `governance-verdict.json` — consistent with `docs/staged-command-surface.md` and ADR-001.
- `docs/adr/adr-001-governance-two-verdicts.md` and `docs/adr/adr-008-resolve-implement-and-review-impl-stage-semantics.md` remain consistent with the staged-command-surface doc on stage boundaries and persisted artifact names; ADR-001 retains its accepted two-verdict governance decision and the informational quality-tag model for `ExecutionResult`, and ADR-008 retains its accepted `implement` / `publish` / `review impl` stage contract and is updated only where its current text now drifts from the staged-command-surface doc.

# In Scope

- Maintain `docs/issue-plans/issue-151.md` as the in-repo canonical tracked plan artifact for this issue, and treat it as part of the governed change surface so its frontmatter, `updated_at`, and approval metadata can be updated alongside the doc edits.
- Update `docs/staged-command-surface.md` only where necessary to:
  - name the "Non-stage context artifacts" sub-section under the "Resume matrix" more explicitly so the run-level vs stage-level split is unambiguous;
  - keep the Artifact Inventory table restricted to stage-produced artifacts and keep the run-level context artifacts in the "Non-stage context artifacts" sub-section;
  - cross-reference ADR-001 for the two-verdict governance contract on `governance-verdict.json` and ADR-008 for the `implement` / `publish` / `review impl` stage contract.
- Update `README.md` "CLI" section per-stage stop descriptions for `create issue`, `review issue`, `plan`, `review plan`, and `implement` (lines 219-247) so they use the same artifact names and the same run-level vs stage-level classification as `docs/staged-command-surface.md`; the `create issue` bullet separates the run-level context artifacts (`run-request.json`, `issue-intake.json`, `issue.md`, `run-record.json`) from the stage-produced `issue-draft.json`.
- Update `docs/architecture.md` "Important Persisted Artifacts" section (lines 296-322) and governance section to use the current `verdict` field names and value sets, and to call out the run-level vs stage-level classification in the same vocabulary as the staged-command-surface doc.
- Update `docs/adr/adr-001-governance-two-verdicts.md` and `docs/adr/adr-008-resolve-implement-and-review-impl-stage-semantics.md` only where their current text now drifts from the staged-command-surface doc on stage boundaries or persisted artifact names; do not reopen the accepted decisions in either ADR.
- Refresh `docs/issue-plans/issue-151.md` `updated_at` on any revision and update its `approved_by`, `approved_at`, and `review_artifact` frontmatter fields when stage-D approval lands.

# Out Of Scope

- Direct-LLM/OpenAI repair-surface cleanup tracked by #145.
- GitHub transport runtime behavior or `GITHUB_TRANSPORT` semantics tracked by #146.
- Stale OpenSWE-era product metadata cleanup tracked by #147.
- Authentication/transport doc separation tracked by #148.
- Review/governance `verdict` terminology normalization tracked by #149 (the contract settled by #149 is the input this issue consumes, not work this issue redoes).
- Generated project-status-report removal/archival tracked by #150.
- `docs/operator-skill.md` rewrite tracked by #152.
- Any change to source code in `src/precision_squad/` or to test files under `tests/`; this issue is documentation-only and inherits the `verdict` contract from #149 verbatim.
- Wholesale rewrites of `README.md`, `docs/architecture.md`, `CONTEXT.md`, `CONTRIBUTING.md`, or `docs/operator-skill.md` beyond the minimum surface required to align artifact names, the run-level vs stage-level classification, and the `verdict` value sets.
- Reopening the accepted decisions in ADR-001 (two-verdict governance + informational quality tag) or ADR-008 (`implement` / `publish` / `review impl` stage contract).
- File renames, stage reordering, artifact lifecycle redesign, or new workflow states; the seven-stage chain and the run-level vs stage-level artifact classification are inputs this issue consumes, not outputs it produces.

# Constraints

- Keep #151 documentation-only and narrowly bounded to aligning `docs/staged-command-surface.md`, the `README.md` "CLI" section, the `docs/architecture.md` governance and "Important Persisted Artifacts" sections, and the two named ADRs; do not expand into broader doc rewrites, code changes, or contract changes.
- The `verdict` value sets are inputs from #149 and ADR-001: review artifacts (`issue-review.json`, `plan-review.json`, `impl-review.json`) use `verdict: approved | changes_requested | blocked`, and `governance-verdict.json` uses `verdict: approved | blocked`. The doc edits must adopt these value sets verbatim, not redefine them.
- `docs/staged-command-surface.md` is the source of truth for the stage chain vocabulary used in this issue. The `README.md` "CLI" section and `docs/architecture.md` governance/artifact sections are aligned to the staged-command-surface doc, not the reverse.
- The "Non-stage context artifacts" sub-section in `docs/staged-command-surface.md` is the canonical run-level artifact inventory. The Artifact Inventory table is restricted to stage-produced artifacts. The two are named distinctly in headings and are not silently merged.
- The canonical tracked plan artifact must live in-repo at `docs/issue-plans/issue-151.md` and is itself part of the governed change surface. Implementation review for #151 must not pass until the tracked plan records actual stage-D approval metadata in its `approved_by`, `approved_at`, and `review_artifact` frontmatter.
- Do not modify GitHub issues, PRs, run artifacts, or unrelated workflow behavior while resolving this issue.
- Do not modify the umbrella issue #144 or any other open/approved sub-issue's issue body; this plan is contained to its own tracked artifact and the files listed in `change_scope.files`.
- The umbrella issue #144 listed #151 as blocked by #149. #149 has since been closed, so that gate is satisfied; this plan is not blocked and may proceed.

# Proposed Approach

First materialize `docs/issue-plans/issue-151.md` as the canonical tracked plan artifact so downstream doc edits are governed in-repo, then align the three doc surfaces in the order that minimizes cross-doc churn.

1. In `docs/staged-command-surface.md`, keep the Artifact Inventory table restricted to stage-produced artifacts and tighten the heading on the run-level artifact sub-section so the "Non-stage context artifacts" label is unambiguous. Cross-reference ADR-001 for the two-verdict governance contract on `governance-verdict.json` and ADR-008 for the `implement` / `publish` / `review impl` stage contract; do not rewrite the per-stage Inputs/Outputs or gate behavior that the doc already encodes correctly per the Stage B verification.

2. In `README.md` "CLI" section, rewrite the per-stage stop descriptions for `create issue`, `review issue`, `plan`, `review plan`, and `implement` (lines 219-247) so they match the staged-command-surface doc's vocabulary. The `create issue` bullet explicitly separates the run-level context artifacts (`run-request.json`, `issue-intake.json`, `issue.md`, `run-record.json`) from the stage-produced `issue-draft.json`; the `review issue`, `plan`, and `review plan` bullets name the single stage-produced review or plan artifact they emit; the `implement` bullet lists the stage-produced artifacts without the run-level ones, matching the Artifact Inventory row for `implement`.

3. In `docs/architecture.md`, update the "Important Persisted Artifacts" section (lines 296-322) to use the same run-level vs stage-level vocabulary as the staged-command-surface doc, and update the governance section so the `verdict` value sets are stated explicitly for review artifacts (`approved | changes_requested | blocked`) and `governance-verdict.json` (`approved | blocked`); cross-reference ADR-001 for the governance contract and ADR-008 for the `implement` / `publish` / `review impl` stage contract.

4. In `docs/adr/adr-001-governance-two-verdicts.md`, make any minor wording change needed so the ADR's description of `governance-verdict.json` and the review/governance value sets reads in the same vocabulary as the staged-command-surface doc; do not reopen the accepted two-verdict decision or the informational quality-tag model. In `docs/adr/adr-008-resolve-implement-and-review-impl-stage-semantics.md`, make any minor wording change needed so the `implement` / `publish` / `review impl` stage boundary text matches the staged-command-surface doc's persisted-artifact names; do not reopen the accepted stage contract.

5. After all doc edits, sweep the four files end-to-end to confirm: (a) every review artifact name uses `verdict`; (b) `governance-verdict.json` uses `verdict: approved | blocked`; (c) the run-level vs stage-level artifact classification is consistent across the three doc surfaces; (d) ADR-001 and ADR-008 cross-references are present where they govern the contract; and (e) no active doc still uses the old "stage artifacts" or "run-provenance artifacts" wording from the original issue body.

6. Refresh `docs/issue-plans/issue-151.md` `updated_at` on each revision and update `approved_by`, `approved_at`, and `review_artifact` once stage-D approval lands, so the plan artifact remains the authoritative tracked plan for this issue.

# Impacted Areas

- `docs/staged-command-surface.md` — Artifact Inventory table scope, "Non-stage context artifacts" sub-section heading clarity, ADR-001/ADR-008 cross-references
- `README.md` — "CLI" section per-stage stop descriptions (lines 219-247) for `create issue`, `review issue`, `plan`, `review plan`, and `implement`
- `docs/architecture.md` — governance section and "Important Persisted Artifacts" section (lines 296-322)
- `docs/adr/adr-001-governance-two-verdicts.md` — wording on `verdict` value sets consistent with staged-command-surface doc (accepted decision preserved)
- `docs/adr/adr-008-resolve-implement-and-review-impl-stage-semantics.md` — wording on `implement` / `publish` / `review impl` stage contract consistent with staged-command-surface doc (accepted decision preserved)
- `docs/issue-plans/issue-151.md` — canonical tracked plan artifact for this issue

# Validation Plan

- Verify `docs/staged-command-surface.md` Artifact Inventory table lists only stage-produced artifacts and the "Non-stage context artifacts" sub-section is the only place run-level context artifacts (`run-request.json`, `issue-intake.json`, `issue.md`) are inventoried; the sub-section is named explicitly in the doc's heading text and is not silently merged into the Artifact Inventory table.
- Verify each review stage description in `docs/staged-command-surface.md` continues to name `verdict` and the same tri-state value set as ADR-001's review surface, and `governance-verdict.json` is described as two-state.
- Verify the `README.md` "CLI" section per-stage stop descriptions (the `create issue`, `review issue`, `plan`, `review plan`, and `implement` bullets at lines 219-247, under the staged `repair issue` command) use the same artifact names and the same run-level vs stage-level classification as `docs/staged-command-surface.md`; the `create issue` bullet separates the run-level context artifacts from the stage-produced `issue-draft.json`.
- Verify `docs/architecture.md` "Important Persisted Artifacts" section uses the same artifact names as the staged-command-surface doc, and the governance section states the `verdict` value sets (`approved | changes_requested | blocked` for review artifacts, `approved | blocked` for `governance-verdict.json`) consistent with ADR-001.
- Verify `docs/adr/adr-001-governance-two-verdicts.md` and `docs/adr/adr-008-resolve-implement-and-review-impl-stage-semantics.md` remain consistent with the staged-command-surface doc on stage boundaries and persisted artifact names; both ADRs retain their accepted status and decision text and were not reopened.
- Grep the active doc surface for the original issue's stale wording (`stage artifacts`, `run-provenance artifacts`) and confirm it no longer appears in `README.md`, `docs/staged-command-surface.md`, or `docs/architecture.md`.
- Verify `docs/issue-plans/issue-151.md` exists in the repository, is within declared `change_scope.files`, has its `updated_at` refreshed on creation, and that implementation review does not pass until actual stage-D approval metadata has been recorded in its `approved_by`, `approved_at`, and `review_artifact` frontmatter.

# Risks

- Doc cleanup could drift into a wholesale README, architecture, or operator-skill rewrite; mitigate by limiting edits to the four named files and the specific vocabulary alignment required by this issue, and by treating #152's operator-skill rewrite as the proper home for any larger refresh.
- Cross-doc wording could drift again after this issue; mitigate by anchoring the run-level vs stage-level classification and the `verdict` value sets to `docs/staged-command-surface.md` and ADR-001, and by making the README and architecture sections reference the staged-command-surface doc rather than redefining the classification.
- Touching the named ADRs could reopen their accepted decisions; mitigate by editing only the wording that aligns artifact names and `verdict` value sets with the staged-command-surface doc, leaving the accepted status, decision text, and rationale sections in both ADRs untouched.
- The `create issue` bullet in the README could lose the run-level vs stage-level separation while aligning to the staged-command-surface doc; mitigate by explicitly calling out the separation in the Proposed Approach and validating it as a separate bullet check.

# Open Questions

- None at planning time. The vocabulary to align (run-level context artifacts vs stage-produced artifacts; `verdict: approved | changes_requested | blocked` for review artifacts; `verdict: approved | blocked` for `governance-verdict.json`) is fixed by `docs/staged-command-surface.md` and ADR-001 and does not require a plan revision.

# Approval Notes

This plan is the canonical tracked implementation source for issue #151 and is itself part of the governed in-repo change surface. It is documentation-only and intentionally narrow: it aligns the four active doc surfaces on the `verdict` contract settled by #149 and on the run-level vs stage-level artifact classification already encoded in `docs/staged-command-surface.md`, without expanding into broader doc rewrites covered by sibling sub-issues of #144, any source code or test changes, or a reopening of the accepted decisions in ADR-001 and ADR-008.

The umbrella issue #144 listed #151 as blocked by #149. #149 is now closed, so that gate is satisfied and this plan is not blocked. The actual stage-D approval outcome must be recorded in this file's `approved_by`, `approved_at`, and `review_artifact` frontmatter before downstream implementation review for #151 is treated as passing.