# ADR-005: Standardize the Repair Agent Seam Around Tool Adapters, OpenCode First

## Status

Accepted

## Date

2026-05-11

## Supersedes

[ADR-002: LLM Abstraction - Direct API Over Agent Binary](./adr-002-llm-abstraction.md)

## Context

`precision-squad` is being built primarily for developers who already work inside coding tools such as `OpenCode`, Codex-style agents, Claude Code style tools, or editor-integrated agents.

That changes what the repair seam should optimize for.

- The system's value is not owning one model transport or one SDK wrapper.
- The system's value is orchestrating a reliable repair-agent workflow around intake, execution contracts, QA, governance, publishing, and review.
- Different coding tools may sit on top of different model providers, but that provider choice is downstream of the repair seam rather than the seam itself.

ADR-002 moved the system toward an explicit adapter interface, but it chose the wrong primary axis. It treated direct LLM SDK access as the main path and external coding tools as the compatibility path.

That is now the wrong default for this project.

We considered three broad directions:

1. keep the direct LLM SDK path as the primary repair implementation
2. support both direct SDKs and tool-backed agents as equal first-class primary paths immediately
3. standardize the seam around tool-backed repair-agent adapters first, with `OpenCode` as the first implementation and other tool adapters following the same interface

Option 3 best matches the product direction, reduces premature provider coupling, and keeps the repair seam focused on the workflow role that matters externally.

## Decision

Standardize the repair-agent seam around tool-backed adapters.

The external interface remains one repair-agent abstraction, but the abstraction now represents a coding tool adapter rather than a direct model SDK path.

### Primary Seam

The system continues to expose one adapter contract to orchestration.

- orchestration chooses a repair-agent implementation
- the adapter hides tool-specific invocation, prompt packaging, output capture, and result projection
- the rest of the system consumes the same external repair-stage behavior regardless of which tool is selected

This keeps the external seam focused on repair behavior rather than model-provider plumbing.

### First Implementation

`OpenCode` is the first supported repair-agent implementation.

- `OpenCodeRepairAdapter` is the first concrete adapter behind the shared seam
- it is the first path the package is validated against
- it is not a privileged architectural special case; it is simply the first implementation

### Future Implementations

The seam is intentionally tool-neutral.

- future adapters may target Codex-style tools, Claude Code style tools, editor-integrated agents, or other coding-agent runtimes
- the interface should not encode `OpenCode`-specific naming, assumptions, or artifacts beyond what every implementation must provide
- adding a new tool adapter must not require reworking orchestration, QA, governance, or publishing semantics

### Direct LLM SDK Path

Direct LLM SDK integration is deferred and removed from the active primary path.

- the project does not standardize on `openai` or another direct SDK as the main repair implementation
- direct SDK support is not forbidden forever, but it is not the current architecture target
- if a future direct SDK path is introduced, it must fit the same honest external repair semantics as every other implementation and must justify itself with a new ADR or ADR update

### CLI and Configuration Meaning

The operator-facing selection surface should describe repair-agent implementations, not direct SDK vendors.

- CLI and config values should name tool-backed implementations
- the selection surface should stay stable even if a tool changes its internal provider stack
- compatibility aliases may exist when needed, but the canonical naming should reflect the repair-agent tool, not a model SDK brand

## Rationale

### Why Move the Seam Upward

The important external question is not "which SDK did we call?" It is "which repair-agent runtime performed the repair work?"

- developers reason about coding tools, not raw provider clients
- operator setup and troubleshooting happen at the tool boundary
- provider choice inside a tool is an implementation detail unless the architecture explicitly needs to expose it

This makes the tool boundary the more honest primary seam.

### Why OpenCode First

`OpenCode` is the tool currently used to operate and test the package.

- it gives the project one real execution path to validate first
- it keeps early implementation scope bounded
- it avoids speculative abstraction over multiple unvalidated tool integrations at once

Choosing `OpenCode` first does not mean choosing `OpenCode` only.

### Why Not Keep Direct SDKs as the Default

A direct-SDK-first architecture would couple the package to one provider path before that path is the real operating environment.

- it pushes the seam toward model transport details too early
- it adds dependency and maintenance burden that the product does not currently need
- it risks solving a lower-level problem than the one operators actually experience

### Why Keep One Shared Interface

The tool implementations may vary, but the rest of the system should not.

- one shared interface keeps orchestration stable
- tests can still use mock adapters against the same contract
- new tool implementations remain additive rather than architectural rewrites

## Trade-offs

### What We Lost

- Direct provider control as the primary path.
- A simpler story for pure API mocking.
- Some short-term generality while `OpenCode` is the only validated implementation.

### What We Gained

- A seam that matches the operator environment.
- Less premature provider coupling.
- Clearer future extensibility.
- A better fit for a workflow whose value is orchestration rather than provider transport.

## Consequences

- ADR-002 is superseded; direct LLM SDK integration is no longer the active default architecture.
- The codebase should remove or retire the direct LLM adapter path from active scope.
- The adapter contract and naming should emphasize tool-backed repair-agent implementations.
- `OpenCodeRepairAdapter` remains the first concrete implementation and the first validation target.
- Future adapters for other coding tools should be added behind the same seam rather than by branching orchestration logic.
- CLI, config, docs, and tests should describe repair-agent tool selection rather than direct SDK vendor selection.

## Implementation Plan

### Affected Paths

- `docs/adr/adr-002-llm-abstraction.md`
- `docs/implementation-plan.md`
- `src/precision_squad/cli.py`
- `src/precision_squad/repair/__init__.py`
- `src/precision_squad/repair/adapter.py`
- `src/precision_squad/repair/llm_adapter.py`
- tests covering adapter selection, CLI semantics, and repair-adapter imports

### ADR and Docs Updates

- mark ADR-002 as superseded rather than rewriting its history
- update implementation and architecture docs so they describe tool-backed adapters as the primary seam

### Adapter Surface

- keep one shared adapter protocol for orchestration
- avoid naming that implies one direct model provider is the canonical path
- ensure `OpenCodeRepairAdapter` remains one implementation of the shared seam, not a special case in orchestration

### Remove Direct SDK Path from Active Scope

- remove or retire the direct LLM adapter implementation from the active repair path
- remove direct-SDK-first CLI/config values from the canonical operator surface
- if compatibility aliases are needed temporarily, document them as compatibility behavior rather than as the target architecture

### Verification Work

Add or update tests so they cover:

- CLI/config selection of tool-backed repair-agent implementations
- `OpenCodeRepairAdapter` remaining reachable through the shared adapter seam
- absence of direct-SDK-first selection semantics from the canonical surface
- adapter imports and exports reflecting the tool-backed architecture
- docs and ADR references pointing to the new active decision

## Verification

- [ ] ADR-002 is marked `Superseded` and points to this ADR
- [ ] The canonical CLI/config repair-agent surface names tool-backed implementations rather than direct SDK vendors
- [ ] `OpenCodeRepairAdapter` remains available through the shared repair-adapter seam
- [ ] Direct LLM SDK integration is removed from the active primary path
- [ ] Tests and docs no longer describe direct-SDK-first behavior as the target architecture

## References

- [CONTEXT.md](../../CONTEXT.md)
- [ADR-002: LLM Abstraction - Direct API Over Agent Binary](./adr-002-llm-abstraction.md)
- [Issue #57](https://github.com/cracklings3d/precision-squad/issues/57)
- [Issue #58](https://github.com/cracklings3d/precision-squad/issues/58)
- [Issue #59](https://github.com/cracklings3d/precision-squad/issues/59)
