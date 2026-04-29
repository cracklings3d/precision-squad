# Archived V1 Architecture

This file is retained for historical reference only.

It describes the earlier `OpenSWE`-based architecture that is no longer the active design for `precision-squad`.

The current direction is a docs-first execution model with explicit local setup and QA contracts derived from repository documentation.

The original archived content begins below.

# V1 Architecture

## Purpose

`precision-squad` is the workflow control plane for OpenSWE-backed issue repair.

The product boundary is deliberate:

- `OpenSWE` is the execution substrate
- `precision-squad` is the control plane

This repository should not grow into another prompt-centric multi-agent runtime.

## Operating Decisions

### CLI/Service First

The first delivery surface is a local CLI backed by reusable application code.

Reason:

- smallest path to a usable product
- easiest local validation loop
- future MCP or remote runner support can reuse the same services

### PAT-Only GitHub Auth

V1 supports personal access tokens only.

Reason:

- smallest authentication surface
- enough for local operator-driven execution
- avoids premature GitHub App complexity

### Filesystem Run Store

Run state will be persisted under a local `.precision-squad/runs/<run-id>/` directory.

Reason:

- transparent and debuggable
- enough for replay and inspection
- no database dependency during bootstrap

### OpenSWE Wrapped Behind An Adapter

`precision-squad` should call OpenSWE through a narrow executor seam.

Reason:

- keeps product boundaries clear
- reduces coupling to upstream runtime details
- makes later substrate changes less invasive

## MVP Loop

The first end-to-end run should:

1. accept a GitHub issue reference
2. fetch and normalize issue data
3. classify whether the issue is runnable or blocked
4. create a persisted run record
5. execute work through the OpenSWE-backed repair workflow
6. collect logs and output artifacts
7. apply governance rules
8. prepare publishing output

## Initial Seams

The first implementation should keep these seams separate:

- GitHub intake
- run store
- executor
- evaluation normalization
- governance
- publishing

That separation matters more than feature breadth during bootstrap.
