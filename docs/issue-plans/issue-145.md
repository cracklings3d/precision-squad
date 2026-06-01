---
issue: github.com/cracklings3d/precision-squad#145
title: Remove direct LLM/OpenAI from the active repair-agent surface
status: approved
plan_status: approved
review_status: approved
source: issue
owner: cracklings3d
created_at: 2026-05-31
updated_at: 2026-06-01
approved_by: "canonical-issue-resolver stage-D review"
approved_at: 2026-06-01T06:01:00Z
review_artifact: 'C:\Users\The_u\.opencode\projects\github-com-cracklings3d-precision-squad\runs\canonical-issue-resolver-parallel\cirp-20260601-020131-8bi7ja\reviews\issue-145\loop-2-stage-D.json'
related_branch: issue/145
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/issue-plans/issue-145.md
    - src/precision_squad/cli.py
    - src/precision_squad/repair/__init__.py
    - src/precision_squad/repair/llm_adapter.py
    - pyproject.toml
    - README.md
    - tests/test_cli.py
    - tests/test_config.py
    - tests/test_adapter.py
    - tests/test_llm_adapter.py
  directories:
    - docs/issue-plans
    - src/precision_squad/repair
    - tests
  modules:
    - precision_squad.cli
    - precision_squad.repair
    - precision_squad.repair.llm_adapter
  artifacts:
    - canonical tracked issue plan for #145
    - repair-agent CLI/config validation contract
    - public repair adapter export surface
    - runtime dependency manifest
    - active README repair-agent documentation
---

# Summary

Issue #145 removes the retired direct-LLM/OpenAI repair path from the active repair-agent surface so the repository's current CLI, config, dependency, and documentation contracts reflect the OpenCode-first model that is actually supported. The intended outcome is a narrow cleanup of the active public surface: `vercel-ai` stops being an accepted repair-agent choice, `VercelAIRepairAdapter` stops being part of the active public API, `openai` stops being a required runtime dependency unless a still-supported runtime proves it needs it, and active tests/docs enforce the same contract.

# Problem

The repository still exposes a retired compatibility path as if it were part of the current repair-agent surface. `src/precision_squad/cli.py` still accepts and documents `vercel-ai`, the public repair package still exports `VercelAIRepairAdapter`, `src/precision_squad/repair/llm_adapter.py` still imports `openai`, `pyproject.toml` still requires `openai`, and active tests plus `README.md` still describe or enforce the legacy path. That leaves the user-facing CLI/config surface, public imports, runtime dependency manifest, and active docs/tests out of sync with the current OpenCode-first/tool-backed repair direction.

# Acceptance Criteria

- `vercel-ai` is no longer accepted as an active user-facing repair-agent choice in CLI/config.
- `VercelAIRepairAdapter` is removed from the active public surface, or is retained only behind a temporary internal-only migration path that is not user-facing.
- `openai` is removed from required runtime dependencies unless an active supported runtime still needs it.
- Active docs no longer describe direct LLM repair as current behavior.
- Tests enforce the active OpenCode-first/tool-backed repair-agent surface and no longer encode the retired compatibility path as supported behavior.

# In Scope

- Keep `docs/issue-plans/issue-145.md` as the in-repo canonical governing artifact for this issue, including the plan-file change scope and the approval metadata needed for downstream implementation review.
- Remove the active CLI/config acceptance path for `vercel-ai` in `src/precision_squad/cli.py`, including choice validation, help text, and repair-adapter construction.
- Remove the active public export/import surface for `VercelAIRepairAdapter` from `src/precision_squad/repair/__init__.py` and any CLI entrypoints that currently import it.
- Delete `src/precision_squad/repair/llm_adapter.py` if no active supported runtime needs it, or move any unavoidable retention behind a non-exported migration-only internal path with no CLI/config ingress.
- Remove `openai` from `pyproject.toml` if no remaining active supported runtime imports it.
- Update the minimum active user-facing docs required for this issue, currently `README.md`, so the active repair-agent contract no longer describes direct LLM repair as current behavior.
- Update the focused tests that currently encode the legacy path: `tests/test_cli.py`, `tests/test_config.py`, `tests/test_adapter.py`, and `tests/test_llm_adapter.py`.

# Out Of Scope

- General stale-product-metadata cleanup tracked by #147, including broad ADR or historical plan rewrites.
- GitHub transport semantics tracked by #146.
- `verdict` terminology normalization tracked by #149.
- Rewriting `docs/implementation-plan.md`, `docs/adr/adr-002-llm-abstraction.md`, or other historical/archival material except where a currently active surface would otherwise still present retired behavior as current.
- Introducing a new direct-LLM replacement adapter or expanding the supported repair-agent matrix beyond the current OpenCode-first surface.

# Constraints

- Keep the implementation tightly bounded to the active repair-agent surface and do not broaden into general documentation archaeology.
- `docs/issue-plans/issue-145.md` must exist as a tracked in-repo artifact for this issue; a workspace-only or otherwise untracked copy does not satisfy the governing plan requirement.
- Implementation review for #145 cannot pass until this canonical plan file records the actual stage-D approval metadata in its existing approval/review fields.
- Prefer full removal of the legacy direct-LLM path over compatibility retention.
- If retention is unavoidable, it must be internal-only, non-user-facing, excluded from public exports, and unreachable from CLI/config selection.
- Remove `openai` from required runtime dependencies unless a still-supported active runtime can justify keeping it.
- Do not modify GitHub issues, PRs, run artifacts, or unrelated workflow behavior while resolving this issue.

# Proposed Approach

First, collapse the active repair-agent contract in `src/precision_squad/cli.py` to the supported surface only. That means removing `vercel-ai` from `_REPAIR_AGENT_CHOICES`, removing the adapter factory mapping for `VercelAIRepairAdapter`, and rewriting CLI help/config validation so `repair_agent` accepts only the currently supported values. The same validation path should reject `vercel-ai` the same way it already rejects other unsupported strings.

Second, remove the public direct-LLM adapter surface from `precision_squad.repair`. The preferred implementation is to delete `src/precision_squad/repair/llm_adapter.py` and stop exporting `VercelAIRepairAdapter` from `src/precision_squad/repair/__init__.py`. If implementation discovers a real internal migration-only dependency, move that code behind a non-exported internal path and keep it unreachable from `_build_repair_adapter`, CLI args, config, and `precision_squad.repair.__all__`.

Third, remove the now-unused required runtime dependency from `pyproject.toml` and align the minimum active documentation/test surface. `README.md` should describe only the active supported repair-agent contract. The focused tests that currently assert retired compatibility behavior should be rewritten or removed so they instead prove rejection of `vercel-ai`, absence of public `VercelAIRepairAdapter` exposure, and absence of a required `openai` runtime dependency unless an active supported runtime still justifies it.

Finally, keep this file materialized in-repo as part of the governed implementation surface for #145. Before a later implementation review can pass, this canonical tracked plan must still be present at `docs/issue-plans/issue-145.md` and must be updated with the actual stage-D approval metadata in its frontmatter and approval notes.

# Impacted Areas

- `docs/issue-plans/issue-145.md`
- `src/precision_squad/cli.py`
- `src/precision_squad/repair/__init__.py`
- `src/precision_squad/repair/llm_adapter.py` (preferred deletion; otherwise internal-only migration retention)
- `pyproject.toml`
- `README.md`
- `tests/test_cli.py`
- `tests/test_config.py`
- `tests/test_adapter.py`
- `tests/test_llm_adapter.py` (preferred deletion if the module is removed)

# Validation Plan

- Verify `docs/issue-plans/issue-145.md` exists in the repository as the canonical tracked plan artifact for #145, remains within declared change scope, and is updated with the actual stage-D approval metadata before treating implementation review as passable.
- Run focused CLI/config tests proving `repair_agent` accepts only the active supported values and rejects `vercel-ai` in both direct CLI input and config-backed input.
- Verify `_build_repair_adapter` and the public `precision_squad.repair` package no longer expose `VercelAIRepairAdapter` as an active public surface; if a migration-only path remains, verify it is not reachable through user-facing selection or public exports.
- Verify `pyproject.toml` no longer lists `openai` in required runtime dependencies unless an active supported runtime still imports it after the cleanup.
- Verify `README.md` no longer describes `vercel-ai` or direct LLM repair as a current supported behavior.
- Run the targeted test files updated for this issue and confirm no remaining expectations treat `vercel-ai`, `openai`, or `VercelAIRepairAdapter` as active supported surface area.

# Risks

- Removing the public adapter surface could break an undisclosed internal caller; mitigate by preferring deletion but allowing only a strictly internal, non-exported migration-only retention path if an actual dependency is discovered.
- Doc overlap with #147 could widen scope; mitigate by limiting documentation edits to the minimum active current-behavior surface required for #145.
- Test cleanup could accidentally remove useful guardrails; mitigate by replacing legacy-support assertions with explicit rejection and public-surface-removal assertions.

# Open Questions

- None.

# Approval Notes

This plan is the canonical tracked implementation source for issue #145 and is itself part of the governed in-repo change surface. It intentionally keeps the change surface narrow: active CLI/config acceptance, active public repair-adapter exports, required runtime dependencies, the minimum active README contract, the focused tests that currently preserve the retired direct-LLM path, and this tracked plan artifact.

Implementation review for #145 must not pass against a workspace-only or pending-only plan state. The actual stage-D approval outcome must be recorded in this file's review/approval metadata before downstream implementation review is treated as passing.
