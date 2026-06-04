---
issue: github.com/cracklings3d/precision-squad#148
title: Separate authentication wording from transport wording in GitHub documentation
status: approved
plan_status: approved
review_status: approved
source: issue
owner: cracklings3d
created_at: 2026-06-03
updated_at: 2026-06-04
approved_by: issue-plan-reviewer
approved_at: 2026-06-03
review_artifact: ~/.opencode/projects/precision-squad/runs/canonical-issue-resolver-parallel/2026-06-03T00-00-04Z/reviews/issue-148/loop-1-stage-D.json
related_branch: issue/148-auth-vs-transport-docs
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - README.md
    - CONTEXT.md
    - CONTRIBUTING.md
  directories: []
  modules: []
  artifacts:
    - docs/issue-plans/issue-148.md
---

# Summary

Issue #148 reconciles GitHub-facing documentation so that authentication (how credentials are supplied) and transport (how GitHub operations are executed) are described as orthogonal concerns. The intended outcome is that `README.md`, `CONTEXT.md`, and `CONTRIBUTING.md` use the same PAT-versus-`GITHUB_TRANSPORT=auto|mcp|cli` separation and no longer imply that PAT and MCP are mutually exclusive concepts.

# Problem

Active GitHub-facing documentation conflates two orthogonal layers by pairing them as if they were the same kind of V1 scope decision:

- `README.md` "V1 Operating Assumptions" (line 41) states "PAT-only GitHub authentication" as a V1 assumption. Authentication is a credential-supply concern, not a transport concern.
- `README.md` "Non-Goals For V1" (line 48) lists "MCP or remote runner support" as a V1 non-goal. MCP is a transport concern, not an authentication concern; `CONTEXT.md` already documents MCP as a supported `GITHUB_TRANSPORT` value.
- `CONTRIBUTING.md` "Not in Scope for V1" (line 142) repeats the conflation by listing "MCP or remote runner support" as a non-goal.

The "PAT-only authentication" (assumption) + "MCP non-goal" (non-goal) pairing presents authentication and transport as parallel V1 scope items, even though they are independent axes. The V1 scope statements also disagree: `README.md` and `CONTRIBUTING.md` treat MCP as a V1 non-goal, while `CONTEXT.md` documents MCP as a supported transport. This drift blocks readers from forming one consistent mental model of what the V1 system supports.

# Acceptance Criteria

- `README.md` "V1 Operating Assumptions" and "Non-Goals For V1" are rewritten so authentication (credential supply) and transport (how operations are executed) are described in separate, parallel sections, and PAT is no longer paired with "MCP non-goal" as if they were the same kind of decision.
- `CONTEXT.md` "GitHub Transport" section explicitly states that the transport model (`auto|mcp|cli`) is independent of credential supply (PAT).
- `CONTRIBUTING.md` "Not in Scope for V1" no longer lists MCP as a non-goal; MCP is either removed from the non-goal list or moved into a transport-scope statement that aligns with `CONTEXT.md`.
- `README.md`, `CONTEXT.md`, and `CONTRIBUTING.md` agree on the supported model — the same authentication/transport separation is used consistently across all three files.
- No active doc implies PAT and MCP are mutually exclusive concepts; the "PAT-only authentication" + "MCP non-goal" pairing pattern is removed or split.
- The V1 scope statements (Authentication V1 scope = PAT; Transport V1 scope = `auto|mcp|cli`) align with the implemented transport behavior documented in `CONTEXT.md`.
- `docs/issue-plans/issue-148.md` exists in the repository as the canonical tracked plan artifact for this issue, and is itself part of the governed change scope.

# In Scope

- Maintain `docs/issue-plans/issue-148.md` as the in-repo canonical governing plan artifact for this issue.
- Rewrite `README.md` "V1 Operating Assumptions" and "Non-Goals For V1" so authentication (PAT) and transport (`GITHUB_TRANSPORT=auto|mcp|cli`) are stated as independent V1 scope axes rather than paired assumption/non-goal items.
- Update `CONTEXT.md` "GitHub Transport" section to explicitly state that the transport model is independent of credential supply (PAT).
- Update `CONTRIBUTING.md` "Not in Scope for V1" so MCP is no longer listed as a non-goal; relocate it (if still mentioned) to a transport-scope statement that aligns with `CONTEXT.md`, or drop it from the non-goal list entirely.
- Make the cross-file wording on the supported V1 model internally consistent across `README.md`, `CONTEXT.md`, and `CONTRIBUTING.md`.

# Out Of Scope

- Direct-LLM/OpenAI repair-surface cleanup covered by #145.
- GitHub transport runtime behavior or `GITHUB_TRANSPORT` semantics covered by #146.
- Stale OpenSWE-era product metadata cleanup covered by #147.
- Review and governance verdict terminology normalization covered by #149.
- Broader product rewording, operator-guide refresh, or wholesale `README.md` / `CONTEXT.md` / `CONTRIBUTING.md` rewrites beyond the minimum authentication/transport separation required by this issue.
- Changing transport implementation, `GITHUB_TRANSPORT` value set, or MCP/CLI runtime behavior.
- Any code, configuration, dependency, or runtime behavior change — this issue is documentation-only.

# Upstream

- Issue #148 declares "Blocked by #145" in the issue body. As of this revision, #145 is already closed (completed), so the relationship is historical rather than an active gate. The implementer must still confirm #145 is resolved/merged in the target branch before starting any of the doc edits in this plan; if #145 is not yet on the base, the implementer must merge #145 first so that the authentication/transport doc rewrites here are not applied on a base that does not yet include the direct-LLM/OpenAI repair-surface cleanup #145 owns. Recording the relationship here keeps the in-repo plan consistent with the issue's "Blocked by" declaration and prevents the implementer from applying #148 on top of a base that is missing #145.

# Constraints

- Keep #148 narrowly limited to separating authentication wording from transport wording in active GitHub-facing documentation; do not expand into broader documentation rewrites, code changes, or transport runtime work.
- Treat `CONTEXT.md` "GitHub Transport" as the source of truth for the supported transport model (`auto|mcp|cli`); other active docs must be brought into agreement with it, not the reverse.
- The canonical tracked plan artifact must remain in-repo at `docs/issue-plans/issue-148.md` and must itself be part of the governed change scope.
- Implementation review for #148 must not pass until the tracked plan records actual stage-D approval metadata in its `approved_by`, `approved_at`, and `review_artifact` frontmatter.
- Do not modify GitHub issues, PRs, run artifacts, or unrelated workflow behavior while resolving this issue.
- The new wording must keep the V1 scope statement structurally separable: an authentication V1 scope statement and a transport V1 scope statement must each be readable on their own without coupling.

# Proposed Approach

1. Update `README.md` "V1 Operating Assumptions" and "Non-Goals For V1" so the authentication assumption is stated in credential-supply terms (e.g., "PAT-only credential supply") and the transport layer is described separately, naming the supported `GITHUB_TRANSPORT=auto|mcp|cli` values from `CONTEXT.md` rather than treating MCP as a non-goal. The result should leave the user able to read the authentication assumption and the transport scope statement independently.
2. Update `CONTEXT.md` "GitHub Transport" section so it explicitly states that the `GITHUB_TRANSPORT=auto|mcp|cli` model is independent of how credentials are supplied (PAT), and the existing token-resolution line is preserved.
3. Update `CONTRIBUTING.md` "Not in Scope for V1" so the "MCP or remote runner support" entry is removed from the non-goal list, and — if MCP is still mentioned in `CONTRIBUTING.md` at all — it appears only in a transport-scope statement that aligns with `CONTEXT.md`.
4. Re-read all three files end-to-end to confirm they agree on the supported V1 model: PAT is the V1 authentication scope, and `GITHUB_TRANSPORT=auto|mcp|cli` is the V1 transport scope.
5. Keep `docs/issue-plans/issue-148.md` materialized in-repo and treat it as part of the governed implementation surface, updating its frontmatter with the actual stage-D approval metadata before downstream implementation review is treated as passing.

# Impacted Areas

- `README.md` — "V1 Operating Assumptions" and "Non-Goals For V1" sections
- `CONTEXT.md` — "GitHub Transport" section
- `CONTRIBUTING.md` — "Not in Scope for V1" section
- `docs/issue-plans/issue-148.md` — canonical tracked plan artifact

# Validation Plan

- Verify `README.md` no longer pairs "PAT-only authentication" with "MCP non-goal" and instead states the authentication V1 scope (PAT credential supply) and the transport V1 scope (`auto|mcp|cli`) as separate, parallel sections.
- Verify `CONTEXT.md` "GitHub Transport" section explicitly states that the transport model is independent of credential supply (PAT).
- Verify `CONTEXT.md` still documents the same `GITHUB_TRANSPORT=auto|mcp|cli` value set already referenced in the current section.
- Verify `CONTRIBUTING.md` "Not in Scope for V1" no longer lists MCP as a non-goal.
- Verify the three files use a consistent authentication/transport separation: PAT is named as the V1 credential-supply mechanism, and `GITHUB_TRANSPORT=auto|mcp|cli` is named as the V1 transport mechanism.
- Grep the active doc surface for the stale pairing pattern (PAT paired with MCP non-goal wording) and confirm it no longer appears in `README.md`, `CONTEXT.md`, or `CONTRIBUTING.md`.
- Verify `docs/issue-plans/issue-148.md` exists in the repository, is within declared change scope, and has its `updated_at` refreshed on creation.

# Risks

- A documentation cleanup could drift into broader doc rewrites or transport runtime work; mitigate by limiting edits to the authentication/transport separation only and excluding #145, #146, #147, and #149 scope.
- Cross-file wording could drift again after this issue; mitigate by anchoring the transport model to `CONTEXT.md` "GitHub Transport" and making `README.md` and `CONTRIBUTING.md` reference that model rather than redefining it.
- The "Not in Scope for V1" list could lose a still-relevant entry during cleanup; mitigate by editing only the MCP/remote-runner line and leaving the other non-goal items untouched.

# Open Questions

- None. The V1 scope statements to align (Authentication V1 scope = PAT; Transport V1 scope = `auto|mcp|cli`) are already specified in the issue body.

# Approval Notes

This plan is the canonical tracked implementation source for issue #148 and is itself part of the governed in-repo change surface. It is intentionally narrow: it does not authorize direct-LLM repair cleanup (#145), transport runtime changes (#146), stale OpenSWE metadata cleanup (#147), or verdict terminology normalization (#149), and it is documentation-only. The actual stage-D approval outcome must be recorded in this file's `approved_by`, `approved_at`, and `review_artifact` frontmatter before downstream implementation review is treated as passing.
