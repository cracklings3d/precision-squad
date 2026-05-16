# Issue 56 Plan: Canonical approved-plan ingress, persistence, retry carry-forward, and strict downstream validation

## Problem Summary

Issue 56 is the minimum enabling seam that turns the approved plan into a real contract artifact for `repair issue`. Today the repo splits approved-plan validation across multiple entry points: persisted artifact shape is validated in `run_store.py`, while CLI-only `issue_ref` checks live in `cli.py`, and downstream review still treats approved-plan presence largely as rendered-text availability. The fix for this issue is to designate one repo-local canonical approved-plan contract seam, require it at fresh-run ingress, persist the validated artifact at run start, reuse it for retry carry-forward, and force both developer and review stages to revalidate the persisted artifact instead of falling back to weaker checks.

## Traceability

- Issue #56 acceptance criteria require the approved plan to behave as one end-to-end contract artifact: validated at ingress, persisted for the run, carried forward on retry, and rejected downstream when structurally invalid.
- Repo-local restatement of the required stage contract for this issue: downstream stages must consume the persisted approved-plan artifact by reloading and validating it at stage entry, and a missing or invalid artifact must stop that stage with an infrastructure failure before the stage runtime is invoked.
- This repo-local restatement is the operative implementation authority for issue 56 in this worktree. Do not depend on unavailable ADR text to fill in missing requirements.
- Scope remains the minimum enabling seam only: make the existing `ApprovedPlan` contract complete and enforceable without redesigning the broader planning workflow.

## Scope Boundaries

### In Scope

- A single canonical validator/helper for approved-plan loading and invariant enforcement
- Fresh-run `repair issue` ingress rules for `--approved-plan-path`
- Early failure semantics that abort before coordinator run creation when a fresh-run plan is missing or invalid
- Run-start persistence to `<run_dir>/approved-plan.json`
- Retry carry-forward with the same precedence and revalidation rules
- Strict developer-stage and review-stage revalidation of persisted approved plans
- Minimal operator-facing discoverability updates for the fresh-run `--approved-plan-path` requirement (CLI help/usage text or equivalent narrow entrypoint docs)
- Focused tests for ingress, retry, persistence, structured coordinator handoff, and downstream rejection paths

### Out of Scope

- New planning workflows, new stage commands, or alternate plan sources
- Broader context-pack redesign beyond the approved-plan artifact already defined for downstream stages
- Changes to issue review semantics, governance policy, publish behavior, or retry limits
- Unrelated cleanup/refactors in repair, retry, coordinator, or review codepaths

## Affected Areas

- `src/precision_squad/cli.py`
- `src/precision_squad/coordinator.py`
- `src/precision_squad/run_store.py`
- `src/precision_squad/repair/orchestration.py`
- `src/precision_squad/repair/adapter.py`
- `src/precision_squad/post_publish_review.py`
- `tests/test_cli.py`
- `tests/test_retry.py`
- `tests/test_run_store.py`
- `tests/test_adapter.py`
- `tests/test_post_publish_review.py`

## Canonical Approved-Plan Contract

The plan artifact for this issue is the existing `ApprovedPlan` schema. For this issue, the canonical loader/validator must live in `src/precision_squad/run_store.py` as the repo-local approved-plan contract seam already shared by persistence and downstream consumers. CLI ingress, coordinator retry carry-forward, developer-stage loading, and review-stage loading must all call that seam instead of keeping separate partial checks. The source artifact must be a JSON object and every downstream-consumed field must be validated, not defaulted opportunistically by individual callers.

- `issue_ref` must exist, must be a non-empty string, and must exactly match the current issue being processed.
- `plan_summary` must exist and must be a non-empty string.
- `implementation_steps` must exist, must be a list, and must contain at least one item.
  - Each item must be a string.
  - Whitespace-only strings are rejected.
  - Non-string items are rejected; callers must not coerce numbers, booleans, objects, or nulls into strings.
- `named_references` must exist and must be a list.
  - `[]` is a canonical valid value; empty named references are allowed when a plan does not need explicit named references.
  - Each item must be either:
    - a non-empty string legacy shorthand, normalized to a `NamedReference` with default type `file`, or
    - an object with a non-empty string `name`, optional `reference_type` constrained to the existing allowed values (`file`, `interface`, `symbol`, `example`), and optional string `description`.
  - Non-list values, empty names, invalid `reference_type`, non-string `description`, or structurally invalid entries are rejected.
  - Persistence must write normalized object form to `<run_dir>/approved-plan.json`; this issue should not preserve legacy string shorthand once the artifact has been loaded into the canonical `ApprovedPlan` model.
- `retrieval_surface_summary` must exist and must be a string.
  - `""` is a canonical valid value; an empty retrieval-surface summary is allowed and means there is no additional retrieval hint for this plan.
  - `null`, objects, arrays, or other non-string values are rejected.
- `approved` must exist as a boolean and must be `true`.

Canonical validity for this issue therefore includes both structurally populated plans and intentionally minimal plans where `named_references` is empty and/or `retrieval_surface_summary` is an empty string. Missing those fields is not valid; explicit empty canonical values are valid.

This helper must be the only supported seam for:

- CLI ingress loading from `--approved-plan-path`
- retry carry-forward from a previous run's `approved-plan.json`
- persisted approved-plan loads from the run store
- developer-stage loading for repair prompt/context construction
- review-stage loading for post-publish review prompt/context construction

Issue 56 should not leave separate partial validators in CLI and run-store codepaths. The implementation must expose a named public cross-module helper from `run_store.py`, and CLI/downstream call sites must stop importing or depending on the private `_read_approved_plan` seam directly.

## Implementation Steps

1. **Create/designate one canonical approved-plan validator/helper**
   - Use `src/precision_squad/run_store.py` as the canonical approved-plan contract seam for this issue, exposing one named public shared loader/validator used by ingress, retry, persistence reloads, and downstream stage entry.
   - Replace the current split behavior with one helper that loads an approved-plan artifact and validates all canonical invariants together.
   - The helper must be used for both file-path ingress and persisted run-directory loads.
   - The helper must take the current `issue_ref` as validation context so `issue_ref` matching is not left as a CLI-only check.
   - The helper must reject artifacts that omit `named_references` or `retrieval_surface_summary`; callers must not silently backfill those downstream-consumed fields.
   - The helper must reject top-level non-object JSON payloads everywhere it is used.
   - CLI and downstream modules must stop using split/private readers or partial validators; the public canonical helper is the only supported cross-module API for approved-plan loading.
   - The structured coordinator handoff boundary must be explicit: coordinator execution receives a fully validated `ApprovedPlan` object, not an unvalidated path or partially checked payload.

2. **Make approved-plan input mandatory for fresh `repair issue` runs**
   - A fresh run without `--approved-plan-path` must fail immediately.
   - A fresh run with a malformed, mismatched, missing-field, malformed `named_references`, invalid `retrieval_surface_summary`, or `approved: false` artifact must fail immediately.
   - This failure surface must be the command-input validation boundary, not a handled coordinator result: the command exits non-zero through the existing CLI command error path, emits an operator-facing approved-plan error message, and occurs before coordinator run creation so no new run record or run directory is created.
   - This issue does not need to suppress issue intake/network lookup; it only requires that coordinator run artifacts are not created for invalid fresh-run ingress.

3. **Define and enforce one precedence rule for fresh runs, retries, and persisted loads**
   - Fresh run: the CLI-supplied approved plan is required and authoritative.
   - Retry with explicit `--approved-plan-path`: the explicitly supplied artifact is authoritative after validation.
   - Retry without explicit path: load the previous run's `approved-plan.json` through the same canonical validator/helper after the previous run record is located.
   - All three paths must reuse the same validation rules and produce the same rejected cases.
   - Retry carry-forward validation must happen before new run creation and before any retry execution continues; this issue does not require reordering issue intake/network lookup ahead of that point.

4. **Persist the validated approved plan at run start**
   - After coordinator run creation succeeds and before executor/repair/publish work begins, persist the selected validated plan to `<run_dir>/approved-plan.json`.
   - Persist exactly the canonical approved-plan artifact for later stage reuse rather than a derived summary.
   - Persistence must write the normalized canonical shape only; if the input used legacy `named_references` string shorthand, the persisted artifact must contain normalized `NamedReference` objects and downstream consumers must only read that normalized persisted shape.
   - Do not add new sidecar artifacts for this issue.

5. **Tighten retry carry-forward failure semantics**
   - Retry without explicit replacement must fail before new run creation if the previous run is missing `approved-plan.json`.
   - Retry without explicit replacement must also fail before new run creation if the persisted artifact is top-level non-object JSON, malformed, has mismatched `issue_ref`, has empty `plan_summary`, has empty/whitespace-only/non-string `implementation_steps`, has malformed `named_references`, has invalid `retrieval_surface_summary`, or has `approved: false`.
   - Retry with explicit replacement must validate the replacement artifact with the same helper before new run creation.
   - Retry operator messaging must distinguish the two failure classes explicitly: one message for missing prior `approved-plan.json`, and a different message for a prior artifact that exists but fails structural validation.

6. **Require strict developer-stage revalidation and context loading**
   - `RepairStage.execute` in `src/precision_squad/repair/orchestration.py` is the developer-stage enforcement seam for approved-plan loading and failure projection.
   - That stage-entry seam must load and validate the current run's persisted `approved-plan.json` through the canonical run-store helper at the very start of `RepairStage.execute`, before workspace creation, clone, reset, checkout, cleanup, or any other repair-stage side effects.
   - Developer-stage entry must reject the full canonical invalid matrix: missing artifact, top-level non-object JSON, malformed JSON, mismatched `issue_ref`, empty `plan_summary`, missing/empty/whitespace-only/non-string `implementation_steps`, missing/malformed `named_references`, missing/invalid `retrieval_surface_summary`, or `approved: false`, instead of silently proceeding from issue text alone.
   - The observable failure contract here must be concrete: `RepairStage.execute` returns the existing repair-stage infrastructure failure result (`RepairResult.status == "failed_infra"`) with an approved-plan load/validation summary, and the short-circuit occurs before any repair-stage workspace mutation and before the repair adapter subprocess/API is invoked.
   - `repair/adapter.py` remains the prompt-construction seam, but it must not become a second independent status-mapping gate for approved-plan validation failures.
   - The developer context should render only the canonical approved-plan content needed by the existing context-pack rules: `plan_summary`, `implementation_steps`, `retrieval_surface_summary`, and named references from the approved artifact. It should not inject broader planning history, issue-thread planning discussion, or any noncanonical plan text.

7. **Require strict review-stage revalidation and context loading**
   - Post-publish review prompt construction must also load the current run's persisted `approved-plan.json` through the same canonical validator/helper.
   - Review-stage entry must reject the exact same canonical invalid matrix used by ingress, retry, and developer-stage validation: missing artifact, top-level non-object JSON, malformed JSON, mismatched `issue_ref`, empty `plan_summary`, missing/empty/whitespace-only/non-string `implementation_steps`, missing/malformed `named_references`, missing/invalid `retrieval_surface_summary`, or `approved: false`.
   - The observable failure contract here must be concrete: stage entry returns the existing review-stage infrastructure failure result (`ReviewAgentResult.status == "failed_infra"`) with an approved-plan load/validation summary, and the review agent runtime must not be invoked when plan loading fails.
   - Review must stop relying on rendered-text presence as the effective validation seam; successful rendering is only allowed after structural and issue-match validation succeed.

8. **Keep the operator boundary discoverable**
   - Because this issue makes `--approved-plan-path` mandatory for fresh runs, the command help/usage surface must say so explicitly.
   - At minimum, the narrow operator-facing seam for `repair issue` must cover both of these surfaces:
    - `repair issue --help` / argparse help text for `--approved-plan-path`, explicitly stating that fresh runs require it and that retry carry-forward is the only no-path exception.
    - the fresh-run missing-flag error surface, with wording that tells the operator the run requires `--approved-plan-path` rather than failing generically.
     - the retry carry-forward rejection surface, with wording that distinguishes `missing prior approved-plan.json` from `prior approved-plan.json failed structural validation`.
   - This issue does not require a broad docs rewrite.

## Validation Plan

- **Canonical validator/helper tests**
  - one shared loader/validator enforces `issue_ref`, `plan_summary`, `implementation_steps`, `named_references`, `retrieval_surface_summary`, and `approved`
  - file-path ingress loads and run-directory loads both exercise the same helper
  - top-level non-object JSON payloads are rejected by the shared helper for both direct file loads and persisted run-directory loads
  - mismatched `issue_ref` and `approved: false` are rejected by the shared helper, not by a one-off caller-only check
   - missing `named_references`, missing `retrieval_surface_summary`, malformed `named_references`, and non-string `retrieval_surface_summary` are rejected by the shared helper
   - empty `plan_summary` is rejected by the shared helper
   - missing `implementation_steps`, empty `implementation_steps`, and `implementation_steps` entries that are whitespace-only or non-string are rejected by the shared helper
   - explicit empty `named_references: []` and `retrieval_surface_summary: ""` are accepted as canonical valid cases
   - legacy string shorthand for `named_references` loads successfully but persistence rewrites it in normalized object form
   - downstream reloads from persisted run artifacts observe only the normalized object form, not legacy string shorthand

- **Fresh-run CLI ingress tests**
  - fresh run succeeds when a valid `--approved-plan-path` artifact is supplied
  - fresh run without `--approved-plan-path` fails
  - fresh run with top-level non-object JSON, malformed JSON, missing required fields, empty `plan_summary`, empty/whitespace-only/non-string `implementation_steps`, malformed `named_references`, invalid `retrieval_surface_summary`, mismatched `issue_ref`, or `approved: false` fails
  - each of those failures occurs before coordinator run creation and leaves no new run directory artifacts
  - the CLI help surface explicitly states the fresh-run requirement and the retry exception
  - the missing-flag error path explicitly tells the operator to supply `--approved-plan-path`

- **Retry precedence and carry-forward tests**
   - retry without explicit replacement carries forward a valid previous `approved-plan.json`
   - retry with explicit replacement uses the new validated artifact instead of the carried-forward one
   - retry without explicit replacement fails before new run creation when the previous artifact is missing, top-level non-object JSON, malformed, mismatched, empty/whitespace-only/non-string in `implementation_steps`, malformed in `named_references`, invalid in `retrieval_surface_summary`, or `approved: false`
   - retry failure messaging distinguishes `missing prior plan artifact` from `prior plan artifact structurally invalid`
   - retry, fresh CLI ingress, and persisted run-store loads all use the same precedence and validation helper

- **Structured coordinator handoff tests**
  - coordinator persists only a validated `ApprovedPlan` selected before execution starts
  - invalid ingress artifacts are rejected before coordinator creates run state

- **Developer-stage tests**
   - `RepairStage.execute` fails as a repair-stage infrastructure failure (`RepairResult.status == "failed_infra"`) when the persisted approved plan is missing
   - `RepairStage.execute` fails with the same `failed_infra` contract when the persisted approved plan is top-level non-object JSON, malformed, has mismatched `issue_ref`, has empty `plan_summary`, has missing/empty/whitespace-only/non-string `implementation_steps`, has missing/malformed `named_references`, has missing/invalid `retrieval_surface_summary`, or has `approved: false`
   - those failures happen before workspace creation, clone/reset, and before `RepairStage.execute` calls `self.adapter.repair(...)`, so no repair-stage side effects or repair agent subprocess/API invocation occurs
   - when valid, the developer context includes the rendered canonical plan content only: summary, implementation steps, retrieval-surface summary, and named references from the approved artifact

- **Review-stage tests**
   - review prompt/context building fails as a review-stage infrastructure failure (`ReviewAgentResult.status == "failed_infra"`) when the persisted approved plan is missing
   - review prompt/context building fails with the same `failed_infra` contract when the persisted approved plan is top-level non-object JSON, malformed, has mismatched `issue_ref`, has empty `plan_summary`, has missing/empty/whitespace-only/non-string `implementation_steps`, has missing/malformed `named_references`, has missing/invalid `retrieval_surface_summary`, or has `approved: false`
   - those failures happen before the review agent runtime is invoked
   - the happy path still works when the persisted artifact is valid and renderable

## Risks And Mitigations

- **Risk: validation drift between ingress, retry, run store, developer, and review paths.**
  - Mitigation: require one canonical validator/helper and test every callsite against it.
- **Risk: fresh-run failures still leave partial run artifacts behind.**
  - Mitigation: make fresh-run validation happen before coordinator run creation and test for absence of new run directories.
- **Risk: downstream stages silently widen scope by pulling broader planning context.**
  - Mitigation: render only the canonical approved-plan artifact fields already allowed by the existing context-pack rules.
- **Risk: operators miss the new mandatory fresh-run input boundary.**
  - Mitigation: make the requirement explicit in CLI help/usage text and pin it in tests.

## Minimum Enabling Seam

This issue should land only the smallest coherent seam that makes approved-plan handling trustworthy end to end: complete canonical validation of the existing `ApprovedPlan` contract, required fresh-run ingress, run-start persistence, retry carry-forward, strict downstream revalidation, and the narrow discoverability updates needed for the new mandatory CLI boundary. Do not widen the change into general planning workflow redesign, schema redesign beyond the current contract, or unrelated context-pack work.
