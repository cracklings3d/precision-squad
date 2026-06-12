---
issue: github.com/cracklings3d/precision-squad#166
title: Migrate from CONTEXT.md to standard CLAUDE.md with cascading prompt support
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
related_branch: issue/166-claude-md-migration
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - CLAUDE.md
    - CONTEXT.md (redirect shim)
    - instructions/governance.md
    - instructions/workflow.md
    - instructions/vocabulary.md
    - instructions/github-transport.md
  directories:
    - instructions/
  modules: []
  artifacts: []
---

# Summary

Migrate the project's bespoke `CONTEXT.md` convention to the standard `CLAUDE.md` format with cascading prompt support. Create `CLAUDE.md` at the workspace root, populate `instructions/` with four topic-specific files, and convert `CONTEXT.md` to a thin redirect shim. Validate that the cascading prompt chain is navigable by a supported agentic runtime.

# Problem

The project currently uses a bespoke `CONTEXT.md` convention. This convention:
- Requires custom parsing logic — not portable across agentic runtimes
- Does not support cascading prompts — topic-specific instructions cannot live in sub-files linked from a root document
- Creates contributor friction — anyone unfamiliar with this project's conventions must read `CONTEXT.md` before contributing

`CLAUDE.md` is a de facto standard supported natively by Claude Code, GitHub Copilot, Cursor, and Windsurf. It natively supports cascading prompts via standard Markdown link syntax.

# Acceptance Criteria

- [ ] `CLAUDE.md` exists at workspace root
- [ ] `CLAUDE.md` links to all four `instructions/` files via `[](./instructions/foo.md)` syntax
- [ ] `instructions/governance.md` exists and contains Governance Verdicts + Quality Tag content migrated from `CONTEXT.md`
- [ ] `instructions/workflow.md` exists and contains Issue-Driven Workflow + Side Issues content migrated from `CONTEXT.md`
- [ ] `instructions/vocabulary.md` exists and contains Repair Agent + Docs Fix Prompt + Project Scope + Graph Refresh Policy content migrated from `CONTEXT.md`
- [ ] `instructions/github-transport.md` exists and contains GitHub Transport content migrated from `CONTEXT.md`
- [ ] `CONTEXT.md` exists but is a redirect shim (header preserved + single line `[](./CLAUDE.md)` redirect)
- [ ] No broken Markdown links to `CONTEXT.md` in any doc file that points to `CONTEXT.md` as a live reference (historical issue-plans are excluded from this requirement)
- [ ] Agentic runtime can read `CLAUDE.md` and follow links to all `instructions/` files ← **CURRENT**

# In Scope

- Create `CLAUDE.md` at workspace root as entry point
- Create `instructions/` subdirectory with four topic-specific files:
  - `instructions/governance.md` — Governance Verdicts, Quality Tag
  - `instructions/workflow.md` — Issue-Driven Workflow, Side Issues
  - `instructions/vocabulary.md` — Repair Agent, Docs Fix Prompt, Project Scope, Graph Refresh Policy
  - `instructions/github-transport.md` — GitHub Transport
- Deprecate `CONTEXT.md` to a redirect shim (preserve header for back-compat, single `[](./CLAUDE.md)` line)
- Update doc files that reference `CONTEXT.md` as a live authority (excluding historical issue-plans)
- Validate cascading prompt behavior

# Out Of Scope

- Run-store schema changes
- Artifact format changes
- Workflow controller logic changes
- Changes to `skills/`, `src/`, `tests/`, or existing ADRs
- Full `CONTEXT.md` removal
- ADR-010 acceptance (ADR-010 remains in `Proposed` status; #166 proceeds in parallel)

# Constraints

- `CONTEXT.md` redirect shim content: preserve original header line, replace body with single redirect line `[](./CLAUDE.md)` — no custom parsing, no multi-line content
- `instructions/*.md` files must be directly mappable to specific `CONTEXT.md` sections (no speculative content)
- Doc-update boundary: update active documentation files (e.g., `.claude/settings.json` if present, root-level docs that reference CONTEXT.md as a current convention); exclude `docs/issue-plans/*` as historical artifacts
- ADR-010 sequencing: #166 merges in parallel with ADR-010 remaining `Proposed`; ADR acceptance is a separate concern

# Proposed Approach

## Phase 1: Create CLAUDE.md and instructions/ directory

1. Create `CLAUDE.md` at workspace root with:
   - Project name and brief purpose statement
   - Link to each `instructions/` file using `[](./instructions/foo.md)` syntax
   - Any top-level guidance that should cascade to all sub-files

2. Create `instructions/governance.md`:
   - Header: `# Governance`
   - Content migrated from `CONTEXT.md` sections: Governance Verdicts, Quality Tag

3. Create `instructions/workflow.md`:
   - Header: `# Workflow`
   - Content migrated from `CONTEXT.md` sections: Issue-Driven Workflow, Side Issues

4. Create `instructions/vocabulary.md`:
   - Header: `# Vocabulary`
   - Content migrated from `CONTEXT.md` sections: Repair Agent, Docs Fix Prompt, Project Scope, Graph Refresh Policy

5. Create `instructions/github-transport.md`:
   - Header: `# GitHub Transport`
   - Content migrated from `CONTEXT.md` section: GitHub Transport

## Phase 2: Convert CONTEXT.md to redirect shim

1. Read existing `CONTEXT.md`
2. Replace body content with single line: `[](./CLAUDE.md)`
3. Preserve header line `# Context` for back-compat with any tooling that references the file by name
4. Result: `CONTEXT.md` contains exactly 2 lines:
   ```
   # Context
   [](./CLAUDE.md)
   ```

## Phase 3: Update doc references

1. Scan for Markdown files (*.md) that contain `[CONTEXT.md]` or `CONTEXT.md` as a live reference
2. Update each reference to point to `CLAUDE.md` or the appropriate `instructions/` file
3. **Excluded**: `docs/issue-plans/*` — these are historical artifacts; their references to `CONTEXT.md` reflect the state at time of authoring and are not live documentation

## Phase 4: Validate cascading prompts

1. Open `CLAUDE.md` in a supported agentic runtime (Claude Code, Cursor, etc.)
2. Verify the agent can navigate to and read each `instructions/` file via the Markdown links
3. Verify content in each `instructions/` file matches the corresponding `CONTEXT.md` section

# Impacted Areas

- `CLAUDE.md` (new file at workspace root)
- `instructions/` (new directory at workspace root)
- `instructions/governance.md` (new file)
- `instructions/workflow.md` (new file)
- `instructions/vocabulary.md` (new file)
- `instructions/github-transport.md` (new file)
- `CONTEXT.md` (modified: body replaced with redirect shim)

# Validation Plan

1. **File existence check**: `CLAUDE.md` and all four `instructions/*.md` files exist at workspace root
2. **Link syntax check**: `CLAUDE.md` contains four valid `[](./instructions/foo.md)` links
3. **Redirect shim check**: `CONTEXT.md` contains exactly the 2-line shim (header + single redirect link)
4. **Content fidelity check**: Each `instructions/*.md` file contains content migrated from its corresponding `CONTEXT.md` section(s)
5. **Cascading prompt check**: Open `CLAUDE.md` in agentic runtime; verify all linked `instructions/` files are reachable and readable
6. **No broken references check**: Active documentation files (excluding `docs/issue-plans/*`) do not contain broken links to `CONTEXT.md`

# Risks

- **ADR-010 sequencing ambiguity**: ADR-010 is `Proposed` but #166 proceeds in parallel. Mitigation: ADR-010 does not need to be `Accepted` before #166 merges; the ADR authorizes the *decision* while #166 handles *implementation*. ADR-010 explicitly states "Issue #166 owns the implementation."
- **Historical issue-plans**: Excluding `docs/issue-plans/*` from doc-update scope means some historical artifacts will still reference `CONTEXT.md`. This is acceptable as those are frozen records, not live documentation.

# Open Questions

- **Doc-update boundary**: Is `docs/issue-plans/*` the correct exclusion set, or are there other historical artifacts that should be excluded?
- **Validation automation**: The cascading prompt validation step requires a human or agentic runtime check. Should a scripted validation (e.g., link checker) be added to the PR checklist?
- **CLAUDE.md top-level content**: Should `CLAUDE.md` contain any content beyond links to `instructions/` files (e.g., project name, purpose statement)?

# Approval Notes

- Stage B review identified five concerns for the planner to resolve:
  1. **Redirect shim content**: Pin to 2-line format (header + single `[](./CLAUDE.md)` redirect line)
  2. **instructions/*.md content**: Pin each file to specific CONTEXT.md sections (documented in In Scope above)
  3. **Doc-update boundary**: Active docs only; exclude `docs/issue-plans/*` as historical
  4. **Validation signal**: Manual or runtime check; cascading prompt chain must be navigable
  5. **ADR-010 sequencing**: #166 proceeds in parallel with ADR-010 in `Proposed` status; ADR acceptance is separate
- Stage B review confirmed issue passes acceptance with the above concerns addressed in this plan
