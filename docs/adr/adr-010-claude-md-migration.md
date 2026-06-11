# ADR-010: Transition from Custom CONTEXT.md to Standard CLAUDE.md

## Status

Proposed

## Date

2026-06-12

## Context

`precision-squad` currently uses a custom `CONTEXT.md` file at the workspace root as the primary mechanism for supplying project-specific context to agentic coding environments. `CONTEXT.md` was introduced to capture domain vocabulary, governance verdicts, workflow semantics, and project-specific conventions in a machine-readable and human-readable form.

However, `CONTEXT.md` is a bespoke convention. It requires custom parsing logic, is not recognized natively by most agentic coding runtimes, and does not participate in the standard cascading prompt hierarchy that most modern agentic development environments support.

[`CLAUDE.md`](https://docs.anthropic.com/en/docs/claude-code/markdown#instructions-for-claude-code) is a de facto standard supported by a wide range of agentic coding environments (Claude Code, GitHub Copilot, Cursor, Windsurf, and others). It uses the same Markdown format but follows a well-documented convention that agentic runtimes recognize and automatically inject into context at the appropriate trigger points.

Key properties of CLAUDE.md relevant to this decision:

- **Cascading prompts**: CLAUDE.md supports hierarchical, cascading instructions. A root-level `CLAUDE.md` can reference sub-files that are loaded conditionally or on-demand. This allows separating stable project invariants (workflow, governance) from volatile session state without requiring a custom loader.
- **Runtime-native**: No custom parsing required — agentic runtimes inject CLAUDE.md automatically.
- **Portability**: Contributors and tools that understand agentic coding environments already understand CLAUDE.md without needing to understand `precision-squad`'s custom conventions.
- **Trigger semantics**: CLAUDE.md is read on every conversation turn by most runtimes, making it more responsive than a static `CONTEXT.md` that requires explicit re-reading.

The transition is motivated by portability and cascading capabilities. The custom CONTEXT.md was correct for its time but is now a friction point for contributors and an integration burden for tooling that expects the standard convention.

## Decision

Outcome: **Go - adopt CLAUDE.md as the standard project context file, deprecate CONTEXT.md, and implement cascading prompt support.**

### Scope of this slice

This ADR authorizes the following for the initial migration slice:

1. Create a root-level `CLAUDE.md` at the workspace root that mirrors the stable content currently in `CONTEXT.md`.
2. Support **cascading prompts** — structured as an `instructions/` subdirectory containing topic-specific files that CLAUDE.md references via Markdown links. For example: `instructions/governance.md`, `instructions/workflow.md`, `instructions/vocabulary.md`.
3. Deprecate `CONTEXT.md` in favor of `CLAUDE.md` — `CONTEXT.md` may be removed or reduced to a thin redirect/compatibility shim pending a follow-on issue.
4. Preserve all existing content: governance verdicts, quality tags, issue-driven workflow, GitHub transport semantics, repair agent contract, and skill references.

### What is out of scope for this slice

- Changes to the run-store schema, artifact formats, or workflow controller logic.
- Changes to existing ADRs or documentation outside the CLAUDE.md migration itself.
- Changes to `skills/` directory or skill invocation conventions.
- Changes to `src/` or `tests/` code.

### Proposed structure

```
CLAUDE.md                    ← root prompt, imports instructions/*
instructions/
  governance.md              ← verdicts, quality tags, approved/blocked semantics
  workflow.md                ← seven-stage workflow, stage ownership, repair contract
  vocabulary.md              ← domain terms, issue vocabulary, artifact naming
  github-transport.md        ← GITHUB_TRANSPORT semantics, credential supply
```

Each `instructions/*.md` is a stable reference unit. `CLAUDE.md` links them via standard Markdown `[](./instructions/foo.md)` syntax, which cascading prompt loaders follow. Exact file names, linking conventions, and load-order are details for the implementation issue.

### Cascade trigger behavior

Cascading prompt loaders (in supported runtimes) typically:
- Load the root `CLAUDE.md` on every conversation turn.
- Resolve and load linked sub-files recursively.
- Respect file-change timestamps to invalidate cached loads.

This means volatile or session-specific content (e.g., current run ID, active repair context) that currently lives in `CONTEXT.md` may need to live elsewhere (run artifacts, environment variables, or a session-scoped prompt prefix) rather than in `CLAUDE.md` itself. This is a detail to resolve in implementation.

## Rationale

### Portability

`CONTEXT.md` is a bespoke convention understood only by `precision-squad`'s tooling. Any contributor or tool that understands agentic coding environments already understands CLAUDE.md without additional onboarding. **This axis supports Go.**

### Cascading prompts

The cascading capability is the primary new capability this transition unlocks. Stable project invariants (governance rules, workflow stages, domain vocabulary) can live in `instructions/*.md` and be loaded on demand. Volatile session state does not need to be merged into a monolithic `CONTEXT.md` and re-read on every turn. **This axis supports Go.**

### Migration cost

The migration is a documentation / file-structure change, not a code change. Content migrates from `CONTEXT.md` to `CLAUDE.md` and `instructions/`. The run-store, artifact schemas, and controller logic are unaffected. **This axis supports Go with minimal risk.**

### Runtime compatibility

Not all agentic runtimes support cascading prompts in the same way. The implementation must confirm that the cascading structure degrades gracefully in runtimes that load only the root file (i.e., the root `CLAUDE.md` must remain self-contained enough to be useful without any sub-files loaded). This is a detail for the implementation issue to validate. **This axis introduces a risk to be mitigated.**

### CONTEXT.md retirement

`CONTEXT.md` currently lives at the workspace root and is referenced by existing ADRs and documentation. Retiring or redirecting it requires updating those references. A compatibility shim (a `CONTEXT.md` that simply points to `CLAUDE.md`) may be the safest first step, with full removal deferred to a follow-on issue. **This axis supports Go via a phased approach.**

## Consequences

### For Go

- `CLAUDE.md` is created at the workspace root with stable content migrated from `CONTEXT.md`.
- `instructions/` subdirectory is created with topic-specific reference files linked from `CLAUDE.md`.
- `CONTEXT.md` is deprecated (retained as a thin redirect shim or removed outright — decision deferred to implementation).
- Documentation files that reference `CONTEXT.md` are updated to reference `CLAUDE.md` or the relevant `instructions/` file.
- No changes to `src/`, `tests/`, `skills/`, or existing ADRs.

### For No-go

- `CONTEXT.md` remains as-is.
- The primary cost is continued friction for contributors and tooling that expect the standard CLAUDE.md convention. The de facto standard is unlikely to shift back toward bespoke context files.

## References

- [CLAUDE.md convention (Anthropic docs)](https://docs.anthropic.com/en/docs/claude-code/markdown#instructions-for-claude-code)
- [CONTEXT.md](./CONTEXT.md) — current custom context file (to be migrated)
- [architecture.md](../architecture.md) — workspace persistence model
- [staged-command-surface.md](./staged-command-surface.md) — workflow stages and repair contract
