---
issue: github.com/cracklings3d/precision-squad#167
title: Add ADR-010 documenting the CONTEXT.md → CLAUDE.md transition decision
status: draft
plan_status: proposed
review_status: pending
source: issue
owner: architect
created_at: 2026-06-12
updated_at: 2026-06-12
approved_by: null
approved_at: null
review_artifact: null
related_branch: issue/167-adr-010-claude-md
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/adr/adr-010-claude-md-migration.md
  directories: []
  modules: []
  artifacts: []
---

# Summary

Create ADR-010 to formally document the decision to transition from the custom `CONTEXT.md` convention to the standard `CLAUDE.md` format with cascading prompt support. The ADR captures the rationale (portability, contributor-friction reduction, native cascading prompt support) and does not authorize any implementation changes — those are owned by issue #166.

# Problem

The project currently uses a bespoke `CONTEXT.md` convention that requires custom parsing logic. This creates friction for contributors familiar with standard agentic coding conventions (Claude Code, GitHub Copilot, Cursor, Windsurf) which natively support `CLAUDE.md`. Additionally, `CONTEXT.md` does not support cascading prompts — topic-specific instructions cannot live in sub-files linked from a root document without custom loader code.

# Acceptance Criteria

- `docs/adr/adr-010-claude-md-migration.md` exists on `master`
- ADR follows the existing `adr-009-fsm-workflow-controller.md` format (Status, Date, Context, Decision, Rationale, Consequences, References)
- ADR explicitly cross-references #166 as the implementation issue
- ADR status is `Proposed` (not yet Accepted)
- PR links to this issue and is mergeable

# In Scope

- Synthesizing the decision rationale from #166's Motivation section (portability, contributor-friction, cascading prompts)
- Authoring the ADR with Context, Decision, Rationale, and Consequences sections
- Establishing ADR-010 status as `Proposed`
- Adding References section pointing to #166 (migration issue) and ADR-009 (format template)
- NOT citing CONTEXT.md as a forward-looking authority

# Out Of Scope

- Implementation of the CLAUDE.md migration (owned by #166)
- Creation of `instructions/` directory or any topic-specific files
- Changes to `CONTEXT.md` itself (will be demoted to redirect shim by #166)
- Any changes to run-store schema, artifact formats, or workflow controller logic
- Any changes to skills/, src/, tests/, or existing ADRs

# Constraints

- ADR must follow the section order and style of ADR-009 (Status, Date, Context, Decision, Rationale, Consequences, References)
- References section must NOT reference `CONTEXT.md` as a forward-looking authority
- Status field must be `Proposed`, not `Accepted`

# Proposed Approach

1. Draft `docs/adr/adr-010-claude-md-migration.md` following ADR-009 format
2. **Context section**: Describe the current state (CONTEXT.md bespoke convention, custom parsing required) and the emergence of CLAUDE.md as a de facto standard
3. **Decision section**: State that the project will adopt CLAUDE.md with cascading prompt support, and that CONTEXT.md will be deprecated (not removed in this slice)
4. **Rationale section**: Synthesize from #166's Motivation:
   - Portability: CLAUDE.md is supported by most agentic coding environments
   - Contributor-friction: familiar convention reduces onboarding
   - Cascading prompts: native support for topic-specific sub-files without custom loader code
5. **Consequences section**: Document what this decision authorizes (the ADR itself) and what it does not authorize (implementation changes)
6. **References section**: Point to #166 (the migration implementation issue) and ADR-009 (the format template)

# Impacted Areas

- `docs/adr/adr-010-claude-md-migration.md` (new file)

# Validation Plan

- File `docs/adr/adr-010-claude-md-migration.md` exists on branch `issue/167-adr-010-claude-md`
- File contains all required sections: Status, Date, Context, Decision, Rationale, Consequences, References
- Status field value is `Proposed`
- References section contains #166 and ADR-009, does not contain CONTEXT.md as forward-looking authority
- PR for this ADR links to issue #167

# Risks

- None identified. This is a documentation-only ADR that does not authorize implementation changes.

# Open Questions

- None. The substantive decision content is already captured in #166's Motivation section.

# Approval Notes

- Stage B review identified that the issue defines the ADR container but not the substantive decision content. The Context/Decision/Rationale prose must be synthesized from #166's Motivation section plus upstream decision context.
- Stage B review also confirmed that references must NOT cite CONTEXT.md as forward-looking authority since #166 will demote CONTEXT.md to a redirect shim.
