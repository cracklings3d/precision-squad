---
issue: github.com/cracklings3d/precision-squad#186
title: Add ADR anchoring README V1 Operating Assumptions for GitHub transport and credential supply
status: draft
plan_status: proposed
review_status: pending
source: issue
owner: architect
created_at: 2026-06-13
updated_at: 2026-06-13
approved_by: null
approved_at: null
review_artifact: null
related_branch: null
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/adr/adr-011-github-transport-and-credential-supply.md
    - README.md
  directories:
    - docs/adr
  modules: []
  artifacts: []
---

# Summary

Create ADR-010 to formally record the V1 operating assumptions for GitHub transport (`auto|mcp|cli`) and PAT-only credential supply, then update README.md to reference it. This addresses the documentation gap identified in the layer-friction audit where neither decision is anchored by a decision record.

# Problem

`README.md:38-48` declares V1 operating assumptions for GitHub transport and credential supply, but no ADR records these as architectural decisions. A contributor asking "why is GitHub App auth excluded in V1?" or "why does the transport distinguish `auto|mcp|cli`?" has no ADR to consult.

# Acceptance Criteria

- [ ] New ADR exists at `docs/adr/adr-011-github-transport-and-credential-supply.md` following the established section shape (`Status`, `Date`, `Context`, `Decision`, `Rationale`, `Consequences`, `References`)
- [ ] ADR records: `GITHUB_TRANSPORT=auto|mcp|cli` with resolution order per `instructions/github-transport.md`
- [ ] ADR records: PAT-only credential supply is the V1 norm; GitHub App auth is explicitly out of scope for V1
- [ ] ADR records: transport and credential supply are independent concerns
- [ ] `README.md:38-48` (V1 Operating Assumptions section) gains a sentence pointing to the new ADR as canonical source

# In Scope

- Authoring `docs/adr/adr-011-github-transport-and-credential-supply.md` following the 7-section baseline (Status, Date, Context, Decision, Rationale, Consequences, References); richer sections (e.g., Trade-offs per ADR-005 precedent) are optional
- Updating `README.md` to cross-reference the new ADR from the V1 Operating Assumptions section

# Out Of Scope

- Changing the V1 Operating Assumptions themselves
- Adding a new transport mode (e.g., `app`)
- Editing `instructions/github-transport.md`

# Constraints

- ADR index resolved to **010** by arithmetic: existing ADRs are 001, 002, 005, 008, 009; next sequential is 010
- ADR must follow the 7-section baseline: Status, Date, Context, Decision, Rationale, Consequences, References (Trade-offs is optional per ADR-005 precedent)
- No production code changes

# Proposed Approach

## Phase 1 — Author ADR-010

**1.1** ← CURRENT
Draft `docs/adr/adr-011-github-transport-and-credential-supply.md` following the 7-section baseline (Status, Date, Context, Decision, Rationale, Consequences, References), drawing context from:
- `README.md:38-48` (V1 Operating Assumptions — transport and credential supply)
- `README.md:50-55` (V1 Non-Goals — GitHub App auth exclusion)
- `instructions/github-transport.md` (transport resolution order `auto|mcp|cli`)

**1.2**
Self-verify ADR-010 section shape matches the 7-section baseline (Status, Date, Context, Decision, Rationale, Consequences, References).

## Phase 2 — Update README Cross-Reference

**2.1**
Add a cross-reference sentence to `README.md:38-48` pointing to ADR-010 as the canonical source for the V1 GitHub transport and credential supply decisions.

**2.2**
Verify the README update does not alter the existing V1 Operating Assumptions text, only adds a reference.

# Impacted Areas

- `docs/adr/adr-011-github-transport-and-credential-supply.md` (new artifact)
- `README.md` (inline reference addition)

# Validation Plan

- [ ] New ADR file exists at `docs/adr/adr-011-github-transport-and-credential-supply.md`
- [ ] ADR contains all 7 baseline sections (Status, Date, Context, Decision, Rationale, Consequences, References)
- [ ] ADR accurately represents the `auto|mcp|cli` transport model and its independence from credential supply
- [ ] ADR explicitly records PAT-only as V1 norm and GitHub App as V1 out-of-scope
- [ ] README.md V1 Operating Assumptions section contains a sentence referencing ADR-010

# Risks

- None identified — purely documentation work with no code or behavior changes

# Open Questions

- None at plan time

# Approval Notes

- ADR index **010** is the next sequential after existing ADRs 001, 002, 005, 008, 009 — no external confirmation needed; arithmetic is deterministic.
