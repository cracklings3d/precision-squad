# ADR-010: CLAUDE.md Migration

## Status

Proposed

## Date

2026-06-12

## Context

The project currently uses a bespoke `CONTEXT.md` convention that requires custom parsing logic. This convention was established to capture governance verdicts, quality tags, workflow definitions, and domain vocabulary in a single document. However, `CONTEXT.md` is a project-specific convention that offers no portability across agentic coding environments.

In parallel, `CLAUDE.md` has emerged as a de facto standard supported by most agentic coding environments — including Claude Code, GitHub Copilot, Cursor, and Windsurf. Unlike `CONTEXT.md`, the `CLAUDE.md` convention natively supports cascading prompts: topic-specific instructions can live in sub-files (e.g., `instructions/*.md`) that the root `CLAUDE.md` links via standard Markdown syntax, without any custom loader code.

This shift represents both a portability opportunity and a contributor-friction reduction. Any contributor familiar with agentic coding workflows already understands `CLAUDE.md`; `CONTEXT.md` requires project-specific onboarding that provides no lasting value outside this codebase.

## Decision

Outcome: **Adopt `CLAUDE.md` with cascading prompt support; deprecate `CONTEXT.md`**.

The project will transition from the custom `CONTEXT.md` convention to the standard `CLAUDE.md` format. The root `CLAUDE.md` will serve as the entry point, with topic-specific instructions living in a linked `instructions/` subdirectory. `CONTEXT.md` will be deprecated — reduced to a thin redirect shim pointing to `CLAUDE.md` or the relevant `instructions/` file — without full removal in this slice.

**This ADR authorizes only the decision record itself.** Implementation of the migration (creation of `CLAUDE.md`, `instructions/` directory, topic-specific files, and the `CONTEXT.md` redirect shim) is owned by issue #166 and is explicitly out of scope for this ADR.

## Rationale

The decision to adopt `CLAUDE.md` is grounded in three pillars drawn from the migration implementation issue:

### Portability

`CLAUDE.md` is supported as a native convention by most agentic coding environments. This means the project can move between tools without rewriting instruction files. `CONTEXT.md` is a bespoke format with no external tooling support and no ecosystem momentum.

### Contributor-friction

Anyone familiar with agentic coding workflows already knows `CLAUDE.md`. Adopting it eliminates a project-specific learning curve and makes the codebase more accessible to contributors who have not yet read `CONTEXT.md`. Familiar conventions reduce onboarding cost and increase the likelihood of useful contributions.

### Cascading prompts

`CLAUDE.md` natively supports cascading prompts — topic-specific instructions can live in sub-files (`instructions/*.md`) that the root `CLAUDE.md` links via standard Markdown `[](./instructions/foo.md)` syntax, without custom parsing or loader code. This enables modular organization of concern-specific documentation (governance, workflow, vocabulary, GitHub transport) while keeping the root document readable. `CONTEXT.md` does not support this pattern without custom code.

## Consequences

### What this ADR authorizes

- This ADR artifact (`docs/adr/adr-010-claude-md-migration.md`) is produced and committed.
- The decision to adopt `CLAUDE.md` with cascading prompt support is formally recorded.
- `CONTEXT.md` is formally deprecated as a future state (full removal is deferred to a follow-on issue).
- No implementation code, scripts, or file changes are authorized by this ADR.

### What this ADR does NOT authorize

- Creation of `CLAUDE.md` at the workspace root.
- Creation of `instructions/` directory or any topic-specific files.
- Changes to `CONTEXT.md` (it will be demoted to a redirect shim by issue #166).
- Any changes to run-store schema, artifact formats, or workflow controller logic.
- Any changes to `skills/`, `src/`, `tests/`, or existing ADRs.

### Ownership of downstream work

Issue #166 owns the implementation of this decision. That issue will produce `CLAUDE.md`, the `instructions/` directory with topic-specific files, and the `CONTEXT.md` redirect shim. This ADR and issue #166 together complete the full migration slice.

## References

- [Issue #166: Migrate from CONTEXT.md to standard CLAUDE.md with cascading prompt support](https://github.com/cracklings3d/precision-squad/issues/166) — downstream implementation issue
- [ADR-009: FSM Workflow Controller Architecture](./adr-009-fsm-workflow-controller.md) — ADR format template
