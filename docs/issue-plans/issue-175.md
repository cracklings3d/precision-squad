---
status: not-started
phase: 1
updated: 2026-06-13
---

## Goal

Update `## Status` in `docs/adr/adr-009-fsm-workflow-controller.md` from `Proposed` to `Accepted` to match the recorded Go decision, and verify the ADR body contains no wording inconsistent with an Accepted decision.

## Context & Decisions

| Artifact | Decision |
|----------|----------|
| Issue #175 | Change ADR-009 status from `Proposed` to `Accepted` |
| ADR-009 Decision section | "Go - documentation-only migration slice" — decision is already made |
| Issue scope | Documentation-only fix; no code, test, or schema changes |
| Issue out-of-scope | Reopening the FSM decision or implementing the controller in code |

## Phases

### Phase 1 — Update Status and Verify Consistency

**Status: IN PROGRESS**

- [ ] **1.1** ← CURRENT — Change `## Status` value from `Proposed` to `Accepted` in `docs/adr/adr-009-fsm-workflow-controller.md`
- [ ] **1.2** — Audit Context, Decision, Rationale, and Consequences sections for any wording that treats the decision as pending or "being proposed"; flag for revision if found
- [ ] **1.3** — Confirm no "proposed" or "pending" language remains in the four sections after 1.1
- [ ] **1.4** — Stage the change on `issue/175-adr-009-status` for review

## Acceptance Criteria Checklist

- [ ] `## Status` field in `docs/adr/adr-009-fsm-workflow-controller.md` reads `Accepted`
- [ ] No wording in Context treats the decision as pending
- [ ] No wording in Decision treats the decision as pending
- [ ] No wording in Rationale treats the decision as pending
- [ ] No wording in Consequences treats the decision as pending
- [ ] No code, test, or run-store schema changes introduced
- [ ] Change staged on branch `issue/175-adr-009-status`
