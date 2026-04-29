# Archived Precision Squad Session Handoff

This file is retained for historical reference only.

It captures an earlier architecture exploration centered on `OpenSWE`. That direction is now obsolete.

The active design for `precision-squad` is the docs-first local execution model implemented in the current codebase.

The original archived content begins below.

# Precision Squad Session Handoff

This file captures the current conclusions from the `orchestrator` session so the work can continue in the new repository:

- New repo: `https://github.com/cracklings3d/precision-squad`

## 1. Product Direction

The old direction for this repository is no longer the main path.

The new direction is:

**Build `precision-squad` as an OpenSWE-based workflow control system.**

That means:

- `OpenSWE` is the execution substrate
- `precision-squad` is the workflow control plane
- `precision-squad` is not just another prompt bundle or multi-agent role loop

## 2. Core Decision

The recommended path is:

1. Create a new public repository
2. Use `OpenSWE` as the upstream foundation
3. Build a control layer on top of it
4. Keep this repository as a design source, not the product host

The team accepted opening a new repository because the current repository is too far from the new target.

## 3. Why A New Repository Was Chosen

The current `orchestrator` repository is centered around:

- multi-role prompt workflow
- bounded-context handoff
- installer and prompt distribution
- packet/task-style workflow ideas

The new target is centered around:

- GitHub issue/project/PR-driven execution
- OpenSWE environment preparation and evaluation
- run orchestration
- artifact persistence
- governance and merge gating

Those are different core abstractions.

So the least-cost, least-restriction choice is:

**new public repository + OpenSWE as upstream substrate + new control-plane code in the new repository**

## 4. Licensing Conclusion

`OpenSWE` is AGPL-3.0.

Because the new project will also be public on GitHub, the licensing risk is lower than it would be for an internal closed-source product.

The current recommendation is:

- do not over-optimize for license isolation at the beginning
- do not begin with a deep fork unless required
- prefer building a public control-plane layer that integrates with or depends on OpenSWE

## 5. What OpenSWE Is For In The New System

`OpenSWE` should supply the lower-level SWE execution substrate:

- repository environment preparation
- Docker/runtime environment synthesis
- evaluation script generation or execution support
- SWE task execution substrate
- reproducible execution context

`precision-squad` should supply the upper-level control plane:

- GitHub issue intake
- project/workflow control
