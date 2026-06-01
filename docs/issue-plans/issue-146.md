---
issue: github.com/cracklings3d/precision-squad#146
title: Implement real GitHub transport strategies and enforce GITHUB_TRANSPORT semantics
status: approved
plan_status: approved
review_status: approved
source: issue
owner: cracklings3d
created_at: 2026-05-31
updated_at: 2026-06-01
approved_by: "canonical-issue-resolver stage-D review"
approved_at: 2026-06-01T02:03:00Z
review_artifact: "C:/Users/The_u/.opencode/projects/github-com-cracklings3d-precision-squad/runs/canonical-issue-resolver-parallel/cirp-20260601-020131-8bi7ja/reviews/issue-146/loop-2-stage-D.json"
related_branch: issue/146
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - docs/issue-plans/issue-146.md
    - CONTEXT.md
    - src/precision_squad/github_client.py
    - src/precision_squad/github_transport.py
    - tests/test_github_client.py
    - tests/test_github_transport.py
  directories:
    - docs/issue-plans
    - src/precision_squad
    - tests
  modules:
    - precision_squad.github_client
    - precision_squad.github_transport
  artifacts:
    - Canonical tracked plan artifact for issue #146 with stage-D approval metadata
    - GitHub issue/write runtime transport strategy contract
    - GITHUB_TRANSPORT runtime enforcement and validation matrix
---

# Summary

Issue #146 exists because `resolve_github_transport()` already normalizes and caches `GITHUB_TRANSPORT`, but `src/precision_squad/github_client.py` still executes through mixed inline `gh` CLI and direct HTTP paths. The intended outcome is a narrow runtime-strategy refactor that makes the selected transport govern every public GitHub client operation, forbids silent HTTP fallback in forced modes, and limits non-code updates to `CONTEXT.md` plus this canonical in-repo plan artifact.

# Problem

`src/precision_squad/github_transport.py` is currently the authority for requested mode normalization, probe order, and per-run caching, but `GitHubIssueClient` and `GitHubWriteClient` do not yet treat its result as an execution boundary. The current client code mixes `gh` CLI helpers and direct HTTP helpers method-by-method, so forced `GITHUB_TRANSPORT=mcp` or `=cli` does not reliably control runtime behavior, and there is no explicit MCP strategy surface spanning the existing public client API.

# Acceptance Criteria

- `src/precision_squad/github_client.py` defines an explicit internal runtime transport boundary selected once from `resolve_github_transport()`, with named concrete CLI and MCP strategy implementations.
- The MCP runtime implementation lives in `src/precision_squad/github_client.py` as the private strategy used when `transport_resolution.selected_transport == "mcp"`; `src/precision_squad/github_transport.py` remains the authority for mode normalization, probe order, and per-run caching.
- Every current public `GitHubIssueClient` and `GitHubWriteClient` operation is either routed directly through the selected runtime strategy or explicitly documented as a convenience wrapper over a transport-governed base method; there are no ungoverned public-method gaps.
- Direct HTTP helpers are not a third runtime-selected transport and are not allowed to act as silent fallback when `GITHUB_TRANSPORT` is forced to `mcp` or `cli`.
- `GITHUB_TRANSPORT=auto` remains MCP-first, gh-CLI-second, error-if-neither, with one selected transport used consistently for the life of each constructed client.
- Validation is a reviewable matrix covering forced `cli`, forced `mcp`, and `auto` behavior across read and write surfaces, including unavailable-transport failures, no-cross-transport guarantees, and per-run selection consistency/caching.
- The canonical tracked plan artifact remains in-repo at `docs/issue-plans/issue-146.md`, and implementation review cannot pass until its stage-D approval metadata (`review_status`, `approved_by`, `approved_at`, `review_artifact`) is updated with the actual approval result.

# In Scope

- Revise and preserve `docs/issue-plans/issue-146.md` itself as a governed in-repo implementation artifact for #146.
- Add a private runtime strategy boundary inside `src/precision_squad/github_client.py` and bind it to `resolve_github_transport()` without changing public client entrypoints.
- Implement named CLI and MCP runtime strategies for the current GitHub client surface.
- Route all current public `GitHubIssueClient` and `GitHubWriteClient` operations through the selected runtime strategy or explicit convenience wrappers over that strategy.
- Remove direct HTTP from runtime-selected fallback behavior so forced-mode failures stay explicit and `auto` stays limited to MCP-first then CLI.
- Strengthen focused tests in `tests/test_github_client.py` and `tests/test_github_transport.py` to prove runtime enforcement, unavailable-transport failures, and selection consistency.
- Keep docs changes limited to active transport semantics centered on `CONTEXT.md`, plus this canonical tracked plan artifact.

# Out Of Scope

- Direct LLM cleanup from issue #145.
- Broader auth-versus-transport docs cleanup from issue #148.
- Verdict naming or governance redesign from issue #149.
- Workflow redesign, broader publish/intake refactors, or unrelated GitHub client cleanup outside the runtime transport seam.
- Public call-site rewrites in intake, publishing, post-publish review, repair orchestration, or other existing callers unless a tiny compatibility fix is strictly required.

# Constraints

- Keep `GitHubIssueClient` and `GitHubWriteClient` public entrypoints stable for existing callers; prefer internal delegation changes over call-site rewrites.
- Preserve `src/precision_squad/github_transport.py` as the authority for mode normalization, probe order, and per-run caching unless a narrow support change is truly required to bind the runtime strategy.
- Forced `GITHUB_TRANSPORT=mcp` and `GITHUB_TRANSPORT=cli` must fail explicitly when unavailable and must not silently execute through another transport path or through direct HTTP.
- `GITHUB_TRANSPORT=auto` must remain MCP-first, gh-CLI-second, error-if-neither, consistent with `CONTEXT.md`.
- Keep the change surface tightly limited to runtime transport strategy behavior plus the minimum active docs/tests needed to match it; do not broaden into #145, #148, or #149.
- Keep docs updates centered on `CONTEXT.md`; the only additional docs artifact governed here is this canonical tracked plan file.
- The canonical tracked plan artifact must remain in-repo and must be updated with actual stage-D approval metadata before implementation review can pass.

# Proposed Approach

## Transport architecture

Add a private runtime boundary in `src/precision_squad/github_client.py` (for example, `GitHubRuntimeTransport`) that is selected once during `GitHubIssueClient.from_env()` and `GitHubWriteClient.from_env()` from the already-cached `GitHubTransportResolution`. That boundary should own the full operation surface required by the current public clients: issue read-with-comments, issue comment create, issue create, open-issue listing for docs remediation lookup, pull-request create/read/update, pull-request draft-state update, issue state update, pull-request merge, and pull-request branch update.

Implement two concrete private strategies behind that boundary:

- `GitHubCliTransportStrategy` in `src/precision_squad/github_client.py`, reusing or extracting the current `gh api` logic as the CLI-owned execution path.
- `GitHubMcpTransportStrategy` in `src/precision_squad/github_client.py`, providing the real MCP-owned execution path for the same operation surface.

`src/precision_squad/github_transport.py` remains responsible only for requested-mode normalization, transport availability probing, probe order, and per-run caching. It must not regain method-level fallback logic after the runtime strategy seam is added.

## Public method coverage checklist

All current public methods are in scope except constructors that only store injected dependencies. Each item below must either dispatch directly through the selected strategy or be an explicit wrapper over a transport-governed base call:

- [ ] `GitHubIssueClient.from_env`
- [ ] `GitHubIssueClient.fetch_issue`
- [ ] `GitHubWriteClient.from_env`
- [ ] `GitHubWriteClient.create_issue_comment`
- [ ] `GitHubWriteClient.create_issue`
- [ ] `GitHubWriteClient.find_open_docs_remediation_issue`
- [ ] `GitHubWriteClient.create_draft_pull_request`
- [ ] `GitHubWriteClient.get_pull_request`
- [ ] `GitHubWriteClient.update_pull_request`
- [ ] `GitHubWriteClient.mark_pull_request_ready`
- [ ] `GitHubWriteClient.get_pull_request_head_branch`
- [ ] `GitHubWriteClient.get_pull_request_head_sha`
- [ ] `GitHubWriteClient.reopen_issue`
- [ ] `GitHubWriteClient.close_issue`
- [ ] `GitHubWriteClient.merge_pull_request`
- [ ] `GitHubWriteClient.close_pull_request`
- [ ] `GitHubWriteClient.update_pull_request_branch`

Explicit exclusions:

- `__init__` methods are not separate runtime operations; they only hold injected token/resolution/strategy state.
- Private helpers such as `_via_gh`, `_via_http`, `_request_json`, and `_extract_*` are not part of the public method checklist, but they must not reintroduce silent cross-transport fallback.
- `get_pull_request_head_branch` and `get_pull_request_head_sha` may remain thin wrappers if they derive data solely from a transport-governed `get_pull_request` result rather than issuing independent transport selection logic.

## Direct HTTP path disposition

The current direct HTTP code paths in `src/precision_squad/github_client.py` are removed from runtime-selected execution for #146. They may be deleted outright or temporarily retained as unreachable private code during the refactor, but they must not remain a third transport choice and must not act as silent fallback after a runtime strategy has been selected.

That means:

- forced `mcp` may use only the MCP strategy and must raise an explicit unavailable-transport error if MCP is not available;
- forced `cli` may use only the CLI strategy and must raise an explicit unavailable-transport error if `gh` is not available;
- `auto` may select MCP first or CLI second during initial resolution only, then must stay on that selected strategy for the lifetime of the client instance;
- mid-call or per-method fallback from selected CLI/MCP execution into direct HTTP is forbidden.

## Documentation and plan governance

Limit documentation edits to the active transport semantics in `CONTEXT.md`. Treat `docs/issue-plans/issue-146.md` itself as part of the governable implementation surface: the file must remain present in-repo, must stay aligned with the final implementation scope, and must receive actual stage-D approval metadata before downstream implementation review can pass.

# Impacted Areas

- `docs/issue-plans/issue-146.md` — canonical in-repo plan artifact and required stage-D approval metadata carrier.
- `src/precision_squad/github_client.py` — private runtime strategy boundary plus concrete CLI/MCP strategy implementations.
- `src/precision_squad/github_transport.py` — existing mode normalization, probe order, and per-run caching contract, with only narrow support changes if needed.
- `tests/test_github_client.py` — method-surface transport enforcement tests and no-cross-transport guarantees.
- `tests/test_github_transport.py` — resolution, forced-mode failure, and cache-consistency assertions that support the runtime seam.
- `CONTEXT.md` — minimal active transport semantics wording, centered on MCP-first auto selection and no silent fallback in forced modes.

# Validation Plan

Run `pytest tests/test_github_transport.py tests/test_github_client.py` with targeted fixtures/mocks that make the selected runtime path observable.

## Runtime behavior matrix

| Scenario | Setup | Read-surface checks | Write-surface checks | Required guarantees |
| --- | --- | --- | --- | --- |
| Forced CLI selected | `GITHUB_TRANSPORT=cli`, CLI available | `fetch_issue` uses CLI strategy only | representative write methods use CLI strategy only | no MCP calls, no HTTP fallback |
| Forced CLI unavailable | `GITHUB_TRANSPORT=cli`, CLI unavailable, MCP may be available | client construction or first governed call fails explicitly | write calls fail with the same forced-mode error | no MCP calls, no HTTP fallback |
| Forced MCP selected | `GITHUB_TRANSPORT=mcp`, MCP available | `fetch_issue` uses MCP strategy only | representative write methods use MCP strategy only | no CLI calls, no HTTP fallback |
| Forced MCP unavailable | `GITHUB_TRANSPORT=mcp`, MCP unavailable, CLI may be available | client construction or first governed call fails explicitly | write calls fail with the same forced-mode error | no CLI calls, no HTTP fallback |
| Auto selects MCP | `GITHUB_TRANSPORT=auto`, MCP available | read methods stay on MCP | write methods stay on MCP | no CLI or HTTP crossover after selection |
| Auto selects CLI | `GITHUB_TRANSPORT=auto`, MCP unavailable, CLI available | read methods stay on CLI | write methods stay on CLI | no MCP or HTTP crossover after selection |
| Auto no transport available | `GITHUB_TRANSPORT=auto`, MCP unavailable, CLI unavailable | explicit transport-unavailable error | explicit transport-unavailable error | no partial execution |
| Per-run consistency/cache | repeated client creation and repeated calls in one run | `transport_resolution` remains consistent with actual selected strategy | write calls keep the same selected strategy without reprobe drift | cache/probe order remains governed by `github_transport.py` |

## Method-surface review checklist

- Verify the strategy boundary covers every public method listed in the checklist above, with no untested public-method escape hatches.
- Verify `mark_pull_request_ready` remains transport-governed rather than issuing an ad hoc direct HTTP patch.
- Verify `get_pull_request_head_branch` and `get_pull_request_head_sha` inherit the selected strategy through `get_pull_request` and do not introduce independent fallback logic.
- Verify read and write assertions include unavailable-transport failures, not just happy-path selection.
- Verify selected transport is fixed per constructed client and does not switch transports between successive public method calls.
- Verify `transport_resolution` reported by the client still matches the strategy that actually executed.
- Verify docs updates stay limited to `CONTEXT.md` plus this plan artifact and describe the tested no-silent-fallback rules.
- Verify implementation review is blocked until this plan file remains in-repo and its stage-D approval metadata is populated with the actual approval outcome.

# Risks

- A partial refactor could leave one or more public methods on legacy inline logic; mitigate with the explicit public-method checklist and method-surface validation review.
- MCP strategy wiring could broaden scope if it leaks call-site changes; mitigate by keeping the new seam private to `github_client.py` and preserving existing client entrypoints.
- Retained private HTTP helpers could be mistaken for allowed fallback behavior; mitigate by making runtime-selected HTTP execution explicitly forbidden in the plan, tests, and `CONTEXT.md` wording.
- Plan/code drift could let implementation proceed without approved governance; mitigate by treating `docs/issue-plans/issue-146.md` as required in-repo scope and gating implementation review on actual stage-D approval metadata.

# Open Questions

- None. This revision fixes the governing plan for #146 by explicitly selecting a private CLI-or-MCP runtime strategy boundary, forbidding silent HTTP fallback, and requiring method-surface validation across all current public client operations.

# Approval Notes

This canonical tracked plan was revised after a failed stage-D review to add the missing runtime transport architecture, full public-method coverage checklist, explicit direct-HTTP disposition, and a reviewable validation matrix. Implementation review must remain blocked until this in-repo plan artifact still exists at `docs/issue-plans/issue-146.md` and its actual stage-D approval metadata is filled in by the approving review (`review_status`, `approved_by`, `approved_at`, and `review_artifact` are intentionally still pending here).
