---
issue: github.com/cracklings3d/precision-squad#153
title: Explore an FSM-based controller architecture for the staged workflow
status: draft
plan_status: approved
review_status: approved
source: issue
owner: cracklings3d
created_at: 2026-06-03
updated_at: 2026-06-03
approved_by: issue-plan-reviewer
approved_at: 2026-06-03
review_artifact: ~/.opencode/projects/precision-squad/runs/canonical-issue-resolver-parallel/2026-06-03T00-00-04Z/reviews/issue-153/loop-1-stage-D.json
related_branch: issue/153-fsm-controller-architecture
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/adr/adr-NNN-fsm-workflow-controller.md
    - docs/issue-plans/issue-153.md
  directories:
    - docs/adr/
  modules: []
  artifacts:
    - docs/adr/adr-NNN-fsm-workflow-controller.md
---

# Summary

Issue #153 evaluates whether the staged workflow's implicit orchestration should be made into an explicit finite-state machine (FSM) controller, with deterministic stage transitions owned by the controller and stage-specific decision-making delegated to the per-stage subagents already defined in `docs/staged-command-surface.md`. The intended outcome is a single, well-grounded Architecture Decision Record at `docs/adr/adr-NNN-fsm-workflow-controller.md` that records a falsifiable go/no-go recommendation against six explicit decision criteria, with no production code and no edits to existing ADRs or active surface documents.

# Problem

The seven-stage workflow (`create issue` -> `review issue` -> `plan` -> `review plan` -> `implement` -> `publish` -> `review impl`) is currently orchestrated implicitly. That implicit orchestration is correct in many places but is not inspectable, is not exercisable as a state model, and conflates "which subagent produced the artifact" with "which transition fired." Downstream consumers of the persisted run state cannot answer "what stage is run X in and why?" without re-deriving the chain from logs, and a transition's testability depends on the LLM-driven subagent that owns its stage rather than on a deterministic controller. We do not yet know whether an explicit FSM model would help, and we do not yet know whether the cost of formalizing the orchestration is worth the gain. The deliverable is therefore a decision, not an implementation: a single ADR that weighs the FSM proposal against the current implicit orchestration on six falsifiable axes and records a justified go/no-go.

# Acceptance Criteria

- A new ADR exists at `docs/adr/adr-NNN-fsm-workflow-controller.md` (the `NNN` placeholder is replaced with the next free ADR index at file creation time; the file name must match the existing `adr-NNN-...` convention used by `adr-001`, `adr-002`, `adr-005`, and `adr-008`).
- The ADR follows the established section shape used by the existing ADRs (`Status`, `Context`, `Decision`, `Rationale`, `Consequences`, `References`) and is written in the same prose style as `adr-001-governance-two-verdicts.md` and `adr-008-resolve-implement-and-review-impl-stage-semantics.md`.
- The current implicit state model and the seven transition points between stages are documented in the ADR with citations to `docs/staged-command-surface.md`, so the ADR stands alone as a self-contained reference for the decision.
- The proposed FSM state set, event alphabet (events such as `stage_succeeded`, `gate_blocked`, `retry_requested`, `verdict_changes_requested`), and transition function are described concretely, with no hand-waving: every state has a name, every event has a name, and every transition is named with `(state, event) -> state` clarity.
- Each FSM transition is mapped to either deterministic controller logic or a designated per-stage subagent, with a one-to-two-sentence rationale per transition.
- Each of the six decision criteria from the issue is addressed in the ADR with a short, falsifiable assessment (not a generic "looks good"), and the go/no-go recommendation is explicitly justified against all six.
- Migration cost, retry/resume impact, and test impact are each addressed in the ADR against the existing persistence model in `docs/architecture.md` and the resume matrix in `docs/staged-command-surface.md`.
- No production code under `src/precision_squad/`, no changes to `docs/staged-command-surface.md`, no changes to `docs/architecture.md`, and no edits to any existing ADR are introduced by this issue; the new ADR file and `docs/issue-plans/issue-153.md` are the only artifacts produced.
- `docs/issue-plans/issue-153.md` exists in-repo as the canonical tracked plan artifact for this issue, and implementation review does not pass until real stage-D approval metadata has been recorded on that tracked plan artifact.

# In Scope

- Author a single new ADR at `docs/adr/adr-NNN-fsm-workflow-controller.md` following the format and section shape of the existing ADRs in `docs/adr/`.
- Inside the ADR: describe the current implicit state model for the seven-stage workflow with citations to `docs/staged-command-surface.md` (covering `create issue`, `review issue`, `plan`, `review plan`, `implement`, `publish`, `review impl` and the transitions between them).
- Inside the ADR: specify the proposed FSM state set, event alphabet, and transition function, written concretely enough that a reviewer can trace `(state, event) -> state` for every transition without guessing.
- Inside the ADR: include a decision table mapping each transition to either deterministic controller logic or a designated per-stage subagent, with a per-row rationale.
- Inside the ADR: assess the proposal against each of the six decision criteria (`stage-transition testability`, `retry/resume behavior`, `gate-verdict clarity`, `migration cost`, `inspectability of run state`, `stage-boundary preservation`) with a falsifiable, single-paragraph assessment per axis.
- Inside the ADR: assess migration cost, retry/resume impact, and test impact against the existing persistence model in `docs/architecture.md` and the resume matrix in `docs/staged-command-surface.md`.
- Inside the ADR: close with a clearly labeled go or no-go recommendation that is justified by the six decision criteria; "go" must specify that the recommendation is conditional on the documentation-only slice described in the migration-cost section, and "no-go" must state the dominant reason.
- Maintain `docs/issue-plans/issue-153.md` as the canonical in-repo tracked plan artifact for this issue, and carry it through real stage-D approval metadata before downstream implementation review passes.

# Out Of Scope

- Any change to source code under `src/precision_squad/`, including the `coordinator`, `run_store`, `governance`, `publishing`, `cli`, `models`, or `post_publish_review` modules.
- Any change to test files under `tests/` or `tests/integration/`; this issue produces no new tests and modifies no existing tests.
- Any modification to `docs/staged-command-surface.md`, `docs/architecture.md`, `docs/operator-skill.md`, `docs/implementation-plan.md`, `CONTEXT.md`, or any active doc other than the new ADR file.
- Any modification, supersession, or deprecation of any existing ADR (`adr-001`, `adr-002`, `adr-005`, `adr-008`); the new ADR is an addition, not an amendment, and the existing `implement` / `publish` / `review impl` boundary fixed by `adr-008` is treated as a constraint, not a design variable.
- Implementing, scaffolding, or stubbing an FSM controller, a transition runner, a state machine interpreter, a state-table loader, or any new orchestration module; the deliverable is a decision artifact only.
- Migration of persisted run artifacts, retroactive re-persistence of legacy runs, or any change to the run-store JSON schema.
- New CI surfaces, new tooling, new CLI flags, or new operator-facing commands tied to FSM concepts.
- Wholesale rewrites of the seven-stage chain (stage reordering, stage merging, stage splitting, new stages, or renamed stages); the ADR may analyze the chain but must not propose changes to it.
- A go/no-go recommendation that is not justified against all six decision criteria; partial justifications are out of scope as a final state of the ADR.

# Constraints

- Keep #153 strictly to a documentation/ADR deliverable: the new ADR file under `docs/adr/` and the tracked plan artifact `docs/issue-plans/issue-153.md` are the only output. Do not produce code, tests, or modifications to existing active docs.
- Treat the existing ADR format (`Status`, `Context`, `Decision`, `Rationale`, `Consequences`, `References`) as a hard contract; the new ADR must use those exact section headings so the ADR index and review process do not have to special-case it.
- Preserve the stage boundaries fixed by `adr-008-resolve-implement-and-review-impl-stage-semantics.md`: `implement` remains local-only (no branch, no PR), `publish` is the boundary that creates a branch and draft PR, and `review impl` reviews the published draft PR. The FSM proposal must be evaluated against these boundaries; it may not propose changing them.
- Preserve the governance rule from `CONTEXT.md` that `approved` is what gates `publish`, and preserve the tri-state review vocabulary (`approved` | `changes_requested` | `blocked`) and the two-state governance vocabulary (`approved` | `blocked`) used by `adr-001` and the artifact schemas in `docs/staged-command-surface.md`.
- Preserve the existing `repair issue --retry-from RUN_ID --from STAGE_NAME` resume contract, the run/attempt split, and the resume matrix in `docs/staged-command-surface.md`; the FSM proposal must be evaluated against these, and any conditional "go" must describe the documentation-only slice needed to keep them intact.
- Every transition in the proposed FSM must be classifiable as either deterministic controller logic or a designated per-stage subagent invocation; a transition that is "both" or "either" is not acceptable in the ADR and must be resolved before the ADR is marked ready for review.
- The go/no-go recommendation must be falsifiable: a reviewer must be able to point to the six decision criteria and say "this axis supports the recommendation" or "this axis contradicts the recommendation" without re-deriving intent from prose.
- Treat `docs/issue-plans/issue-153.md` as the canonical tracked plan artifact; the new ADR must cross-reference it (and vice versa) so the plan and the decision are bound together in the repo.
- Do not modify the umbrella issue #144 or any other open/approved sub-issue's issue body; this plan is contained to its own tracked artifact, the new ADR, and the files listed in `change_scope.files`.

# Proposed Approach

First, confirm that the canonical plan artifact for this issue lives in-repo at `docs/issue-plans/issue-153.md` and that `docs/staged-command-surface.md`, `docs/architecture.md`, and the four existing ADRs in `docs/adr/` are the only authoritative references the new ADR needs to cite. Then, in the new ADR, follow this concrete section shape so the decision is fully grounded:

1. **Status and Date** - mirror the existing ADR header style; status is `Proposed` at file creation, with an explicit "go" or "no-go" outcome recorded in the `Decision` section.
2. **Context** - describe the current implicit orchestration: the seven stages, the designated per-stage subagent for each, the artifact each subagent owns, and the gate verdict (`approved` | `changes_requested` | `blocked`) that the controller uses to decide whether to advance. Cite `docs/staged-command-surface.md` for the stage chain and resume matrix, and cite `docs/architecture.md` for the persistence model.
3. **Decision** - record the chosen outcome (`Go - documentation-only migration slice`, `Go - requires code change`, or `No-go - keep implicit orchestration`) and, if `Go`, name the explicit slice that has to land first. Every transition in the proposed FSM is named with `(state, event) -> state` clarity and is mapped to either controller logic or a designated subagent in a transition table that lives in the same section.
4. **Rationale** - go through each of the six decision criteria from the issue in order, with one falsifiable paragraph per axis. The paragraphs are not a checklist of "good things"; they make a concrete claim (for example, "the `implement` -> `publish` transition becomes testable with a fixed `impl-review.json` fixture and does not require an LLM" or "the FSM preserves the `repair issue --retry-from RUN_ID --from STAGE_NAME` contract because the resume event is a first-class event in the alphabet").
5. **Consequences** - for `Go`, list the documentation-only slice (which `docs/` files change, which existing ADR, if any, gets a follow-up ADR) and the future code-slice envelope (what the eventual implementation must and must not do) without writing the code. For `No-go`, state the dominant reason and the smallest set of follow-up cleanups (for example, "add a state-diagram section to `docs/architecture.md`") that would be useful even without an FSM.
6. **References** - list the existing ADRs (`adr-001`, `adr-002`, `adr-005`, `adr-008`), `docs/staged-command-surface.md`, `docs/architecture.md`, `CONTEXT.md`, and the canonical tracked plan `docs/issue-plans/issue-153.md`.

The ADR is self-contained: a reviewer can read it without opening other docs and still reach the same go/no-go conclusion. The ADR's decision table is the single most falsifiable surface in the deliverable; the Proposed Approach treats it as the artifact's spine and builds the rest of the sections around it.

# Impacted Areas

- `docs/adr/adr-NNN-fsm-workflow-controller.md` (new ADR; the only documentation output of this issue)
- `docs/issue-plans/issue-153.md` (this canonical tracked plan artifact)
- `docs/adr/` (directory into which the new ADR is added; existing ADRs are not modified)

Read-only references (cited by the ADR, not modified):

- `docs/staged-command-surface.md`
- `docs/architecture.md`
- `docs/adr/adr-001-governance-two-verdicts.md`
- `docs/adr/adr-002-SUPERSEDED.md`
- `docs/adr/adr-005-tool-backed-repair-agent-adapters.md`
- `docs/adr/adr-008-resolve-implement-and-review-impl-stage-semantics.md`
- `CONTEXT.md`

# Validation Plan

- Verify `docs/adr/adr-NNN-fsm-workflow-controller.md` exists in the repository, sits in `docs/adr/`, and uses the same section headings (`Status`, `Context`, `Decision`, `Rationale`, `Consequences`, `References`) as the existing ADRs.
- Verify the ADR's `Status` is `Proposed` at file creation, with the go/no-go outcome recorded in the `Decision` section.
- Verify the ADR describes the seven-stage chain (`create issue`, `review issue`, `plan`, `review plan`, `implement`, `publish`, `review impl`) and explicitly cites `docs/staged-command-surface.md` for the stage chain and resume matrix.
- Verify the ADR specifies the FSM state set, event alphabet, and transition function concretely, and that every transition is named in a decision table with a one-to-two-sentence rationale mapping it to controller logic or a designated per-stage subagent.
- Verify the ADR contains one falsifiable paragraph for each of the six decision criteria (`stage-transition testability`, `retry/resume behavior`, `gate-verdict clarity`, `migration cost`, `inspectability of run state`, `stage-boundary preservation`) and that the final go/no-go recommendation is justified against all six.
- Verify the ADR's `Rationale` and `Consequences` sections address retry/resume impact against the `repair issue --retry-from RUN_ID --from STAGE_NAME` contract and the resume matrix in `docs/staged-command-surface.md`, and address migration cost and test impact against the persistence model in `docs/architecture.md`.
- Verify the ADR explicitly preserves the `implement` / `publish` / `review impl` boundaries from `adr-008` and the `approved` / `changes_requested` / `blocked` review vocabulary and `approved` / `blocked` governance vocabulary from `adr-001`.
- Verify a repository-wide diff for this issue shows no changes to `src/precision_squad/`, `tests/`, `docs/staged-command-surface.md`, `docs/architecture.md`, `docs/operator-skill.md`, `docs/implementation-plan.md`, `CONTEXT.md`, or any of the four existing ADRs; the only new file under `docs/adr/` is the new ADR, and the only new file under `docs/issue-plans/` is `docs/issue-plans/issue-153.md`.
- Verify the new ADR cross-references `docs/issue-plans/issue-153.md` and vice versa, so the plan and the decision are bound together in the repo.
- Verify `docs/issue-plans/issue-153.md` exists in-repo, carries the canonical frontmatter from the template, and that implementation review does not pass until fresh stage-D approval metadata has been recorded on that artifact.

# Risks

- The ADR could become hand-wavy on the transition table and event alphabet, undermining the "concrete enough to be falsifiable" promise of the issue; mitigate by treating the decision table as the spine of the ADR and requiring every transition to be named with `(state, event) -> state` clarity before review.
- The ADR could drift into proposing code or stage-chain changes; mitigate by making the `Out Of Scope` and `Constraints` sections explicit in the ADR too, and by treating the existing `adr-008` boundaries and the existing stage chain as inputs to the analysis, not as design variables.
- A "Go" recommendation could be over-claimed and pull future work into a code change that the issue did not authorize; mitigate by requiring "Go" recommendations to specify the documentation-only slice and to defer the eventual code slice to a separate issue.
- A "No-go" recommendation could be under-justified and read as a refusal to engage; mitigate by requiring the dominant reason to be named and the smallest set of follow-up cleanups (for example, an `architecture.md` state-diagram section) to be recorded.
- The new ADR could collide with `adr-001` (governance two-verdicts), `adr-002` (LLM abstraction), `adr-005` (tool-backed repair agents), or `adr-008` (implement/publish/review-impl semantics); mitigate by checking the new ADR against the `Decision` sections of all four existing ADRs during review and recording any tension explicitly in the new ADR's `Rationale` or `Consequences` section.

# Open Questions

- None at planning time. The `NNN` placeholder in the ADR file name is replaced with the next free ADR index at file creation time and is a bookkeeping detail, not a planning decision.

# Approval Notes

This plan governs only the authoring of a single new ADR at `docs/adr/adr-NNN-fsm-workflow-controller.md` plus the maintenance of `docs/issue-plans/issue-153.md` as the canonical in-repo tracked plan artifact. It does not authorize code changes, test changes, modifications to existing ADRs, or modifications to `docs/staged-command-surface.md` / `docs/architecture.md` / `CONTEXT.md`. The existing `implement` / `publish` / `review impl` boundary from `adr-008` and the `approved` / `changes_requested` / `blocked` review vocabulary from `adr-001` are treated as constraints, not as design variables. The canonical plan artifact must receive real stage-D approval metadata before implementation review for #153 may pass.
