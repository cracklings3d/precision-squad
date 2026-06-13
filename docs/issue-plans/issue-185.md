---
issue: github.com/cracklings3d/precision-squad#185
title: ADR References cite empty CONTEXT.md; update to actual vision sources
status: draft
plan_status: proposed
review_status: pending
source: issue
owner: cracklings3d
created_at: 2026-06-13
updated_at: 2026-06-14
approved_by: null
approved_at: null
review_artifact: null
related_branch: null
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - VISION.md
    - CLAUDE.md
    - docs/adr/adr-001-governance-two-verdicts.md
    - docs/adr/adr-002-llm-abstraction.md
    - docs/adr/adr-005-tool-backed-repair-agent-adapters.md
    - docs/adr/adr-008-resolve-implement-and-review-impl-stage-semantics.md
    - docs/adr/adr-009-fsm-workflow-controller.md
  directories:
    - docs/adr
    - instructions
  modules: []
  artifacts: []
---

# Summary

Create a `VISION.md` canonical vision anchor and update five ADRs that currently cite the empty `CONTEXT.md` stub, redirecting their References sections and in-text mentions to the proper vision sources.

# Problem

Five ADRs cite `CONTEXT.md` for vision-level claims, but `CONTEXT.md` is a 2-line stub (`# Context` + redirect link to `CLAUDE.md`). The actual vision content lives in `instructions/governance.md`, `instructions/vocabulary.md`, `instructions/workflow.md`, and `instructions/github-transport.md`. A reviewer trying to verify a cited claim by opening `CONTEXT.md` finds a redirect stub and must discover the canonical source by luck. ADR-009 (Proposed) cannot be promoted cleanly while its cited vision anchor is empty.

# Acceptance Criteria

- [ ] Create `VISION.md` consolidating the following vision-level topics (no stage-ordering content):
  - Governance verdicts and quality tags — sourced from `instructions/governance.md`
  - Repair agent definition and responsibilities — sourced from `instructions/vocabulary.md`
  - Project scope and structure — sourced from `instructions/workflow.md`
  - GitHub transport configuration — sourced from `instructions/github-transport.md`
- [ ] Update all 5 ADR `References` sections to point to `VISION.md` instead of `CONTEXT.md`.
- [ ] Update `CLAUDE.md` to **add** a link to `VISION.md` alongside the existing instruction-file links (augment, do not replace).
- [ ] Rewrite in-text `CONTEXT.md` mentions in the same change as the References sections for all 5 ADRs (e.g., adr-002 line 125, adr-008 line 21, adr-009 lines 121 and 143).
- [ ] Leave `CONTEXT.md` as a redirect stub to `CLAUDE.md`.

# In Scope

- Creating `VISION.md` with consolidated vision content from the four instruction files
- Updating 5 live ADR References sections and in-text mentions
- Adding VISION.md link to CLAUDE.md
- ADR evidence lines: adr-001:86, adr-002:125, adr-005:196, adr-008:21,112, adr-009:121,143,161

# Out Of Scope

- Rewriting ADR `Decision`, `Context`, or `Rationale` sections
- Changing stage ordering or any design decisions
- Modifying `CONTEXT.md` content (remains as redirect stub)

# Constraints

- VISION.md must not contain stage-ordering content (ADR territory per issue body)
- CLAUDE.md must retain existing instruction-file links (augment only)

# Proposed Approach

1. **Create `VISION.md`**: Consolidate vision-level content from four instruction files into a single canonical document. Follow the source order: governance, vocabulary, workflow, github-transport. No stage-ordering content.
2. **Update ADR References sections**: Replace `CONTEXT.md` citations with `VISION.md` in the References sections of all 5 live ADRs.
3. **Update in-text mentions**: Rewrite `CONTEXT.md` citations in ADR body text (lines identified in evidence) alongside their References section updates.
4. **Update CLAUDE.md**: Add `VISION.md` link to the instruction-links section, preserving existing links.
5. **Validate**: Verify all 5 ADRs no longer cite `CONTEXT.md` for vision claims; VISION.md opens correctly.

# Impacted Areas

- `VISION.md` (new file)
- `CLAUDE.md`
- `docs/adr/adr-001-governance-two-verdicts.md`
- `docs/adr/adr-002-llm-abstraction.md`
- `docs/adr/adr-005-tool-backed-repair-agent-adapters.md`
- `docs/adr/adr-008-resolve-implement-and-review-impl-stage-semantics.md`
- `docs/adr/adr-009-fsm-workflow-controller.md`

# Validation Plan

- Run `layer-friction-audit` or equivalent to confirm no remaining `CONTEXT.md` vision citations in 5 live ADRs
- Manual check: open each ADR's References section and verify `VISION.md` link
- Manual check: search for in-text `CONTEXT.md` mentions in updated ADRs (should be zero for vision-level claims)
- Verify `CLAUDE.md` contains both instruction-file links and new VISION.md link

# Risks

- **Risk**: `VISION.md` content drift from source instruction files over time.
  **Mitigation**: Instruction files remain authoritative; VISION.md is a consolidation anchor, not a living copy.
- **Risk**: In-text mentions missed during update (human error).
  **Mitigation**: Systematic search for `CONTEXT.md` pattern in each ADR before/after comparison.

# Open Questions

- **Section ordering**: The issue specifies the four topics to include but not their internal section order within VISION.md. Following the source instruction file order (governance → vocabulary → workflow → github-transport) is the intended approach unless otherwise specified.
- **ADR-009 promotion gate**: The issue notes ADR-009 "cannot be promoted cleanly" due to empty vision anchor. Unclear whether this issue's changes fully unblock promotion or only ease it. Confirmation from governance owner needed before treating ADR-009 as promotion-ready.

# Approval Notes

- Issue explicitly chose **Option A** (create VISION.md) over Option B (scatter citations across instruction files).
- CLAUDE.md augmentation (not replacement) explicitly specified in issue body.
- ADR-002 (adr-002-llm-abstraction.md) is in scope — it is a live ADR at docs/adr/ (not archived), cited at line 125 with CONTEXT.md.
- Review ambiguities about Option A/B fork and CLAUDE.md augmentation are resolved by explicit statements in issue body.
