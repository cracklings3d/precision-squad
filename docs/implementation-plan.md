# Implementation Plan: precision-squad

Phases are ordered by dependency. Within each phase, items are unordered unless one implies another.

---

## Phase 1 — Governance Model Collapse

**Goal:** Remove `provisional` as a governance verdict. Replace with a `quality` tag on `ExecutionResult`. Governance has only `approved` and `blocked`.

### 1.1 — `models.py`

- [ ] In `GovernanceVerdict.status`, remove `"provisional"` from the `Literal`. Keep only `"approved"` and `"blocked"`.
- [ ] In `ExecutionResult`, add field:
  ```python
  quality: Literal["green", "improved", "degraded"] | None = None
  ```
- [ ] In `RepairResult`, add field:
  ```python
  side_issues: tuple[str, ...] = ()
  ```
  (structured as plain string titles; body and labels are surfaced by the coordinator via the publish plan)

### 1.2 — `repair/qa.py` — `_finalize_qa_result`

Refactor to stamp `quality` onto the returned `QaResult` instead of returning `provisional` as `QaResult.status`. The `QaResult.status` can keep `"provisional"` as an internal classification, but the quality tag is what gets projected into `ExecutionResult.quality`.

Current logic:
- Baseline green → final green → `status="passed"` → governance `approved`
- Baseline failed, repair reduced failures → `status="provisional"` → governance `provisional`
- Baseline failed, no improvement → `status="failed"` → governance `blocked`

New logic:
- Baseline green, final green → `quality="green"`
- Baseline green, final failed → `quality="degraded"`
- Baseline failed, repair reduced failures → `quality="improved"`
- Baseline failed, final green → `quality="green"`
- Baseline failed, no improvement or worse → `quality="degraded"`

The quality tag is set in `merge_execution_result` in `repair/orchestration.py` based on `_finalize_qa_result`.

### 1.3 — `governance.py` — `apply_governance`

Remove the `qa_baseline_improved` and `qa_approximated` branches that returned `status="provisional"`. Governance now only returns `approved` or `blocked`.

### 1.4 — `publishing.py` — `build_publish_plan`

- [ ] Remove `verdict.status in {"approved", "provisional"}` condition. Only `approved` creates a draft PR.
- [ ] Remove `context_note` for provisional. Remove `"## Provisional Summary\n"` heading.
- [ ] Blocked verdict already produces `issue_comment` or `follow_up_issue` — no change needed there.

### 1.5 — `coordinator.py` — `RunCoordinator.repair_issue`

- [ ] Remove `exit_code = 5` branch for `provisional`.
- [ ] Pass `quality` from the merged execution result into governance if needed (governance no longer reads detail codes for provisional — quality is informational only).

### 1.6 — `repair/orchestration.py` — `merge_execution_result`

- [ ] Project the quality tag from `qa_result` into the returned `ExecutionResult.quality`:
  - If `qa_result.status == "passed"` → `quality="green"`
  - If `qa_result.status == "provisional"` → `quality="improved"`
  - If `qa_result.status in {"failed", "unrunnable", "failed_infra"}` and baseline was green → `quality="degraded"`
  - If `qa_result.status in {"failed", "unrunnable"}` and baseline was also failing with no improvement → `quality="degraded"`
  - If `qa_result` is None → `quality=None`

### 1.7 — `publish_executor.py` (if it references provisional)

Check `publish_executor.py` for any provisional-specific handling and remove it.

### 1.8 — `docs/project-status-report.md`

Update to reflect the new two-verdict governance model.

---

## Phase 2 — Repair Agent JSON Schema and Side Issues

**Goal:** Repair agent outputs structured JSON validated against a schema. Side issues are surfaced via `side_issues` field on `RepairResult`, included in the blocked run's publish plan.

### 2.1 — `src/precision_squad/data/repair-result-schema.json`

Create the schema:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "summary": {
      "type": "string",
      "description": "What the agent did — one paragraph max."
    },
    "side_issues": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": { "type": "string" },
          "body": { "type": "string" },
          "labels": { "type": "array", "items": { "type": "string" } }
        },
        "required": ["title", "body"]
      }
    }
  },
  "required": ["summary"]
}
```

### 2.2 — `repair/adapter.py` — `_build_repair_prompt`

- [ ] For **docs-remediation issues**: Include `docs-fix-prompt.txt` **inline** in the prompt (read the file content and embed it), not as a file path. The prompt content IS the fix specification.
- [ ] For **non-docs-remediation issues**: If `docs-fix-prompt.txt` exists, read its content and instruct the agent to recommend surfacing the issues as separate GitHub issues via the JSON output schema (side_issues array). Do NOT treat it as a fix prompt.
- [ ] Add instruction: "Output a single JSON object with at least a `summary` field. Optionally include a `side_issues` array."
- [ ] Add the schema (or a summary of it) to the prompt so the agent knows the expected format.

### 2.3 — `repair/adapter.py` — `OpenCodeRepairAdapter.repair`

- [ ] After running the agent, parse the JSON output (extract from stdout — same JSON-event extraction as currently used for transcript).
- [ ] Validate parsed output against the schema.
- [ ] Map `summary` → `RepairResult.summary`.
- [ ] Map `side_issues` → `RepairResult.side_issues` (join titles with newlines, or store as structured data — detail below).
- [ ] If JSON parsing or validation fails, fall back to current behavior (treat as blocked).

### 2.4 — `publishing.py` — `build_publish_plan`

When verdict is `blocked` and `side_issues` is non-empty on the associated `RepairResult`:
- [ ] Include a `follow_up_issue` action in the publish plan for each side issue (or group them into a single follow-up issue with a bulleted list).

---

## Phase 3 — LLM Adapter (Vercel AI SDK)

**Goal:** Replace the `opencode` binary dependency with a direct LLM API call via Vercel AI SDK.

### 3.1 — New `repair/llm_adapter.py`

Create `OpenAIRepairAdapter` (or similar):

- Uses `openai` SDK directly (what Vercel AI SDK wraps) or the `@ai-sdk/openai` package.
- Reads `OPENAI_API_KEY` (or `VERCEL_API_KEY`) from environment.
- Model from `OPENAI_MODEL` env var or parameter override.
- System prompt: fixed instruction to output JSON matching the repair-result schema.
- User prompt: the same content currently passed to `_build_repair_prompt`.
- Calls the LLM with `response_format: { "type": "json_object" }` to encourage JSON.
- Parses and validates response against the schema.
- Writes `repair.stdout.log` with the raw response text.

### 3.2 — `repair/__init__.py` (or `repair/adapter.py`)

Export both `OpenCodeRepairAdapter` and `OpenAIRepairAdapter`.

### 3.3 — `coordinator.py` / `cli.py`

- [ ] Update `RepairDependencies.create_repair_adapter` to return the new adapter when `repair_agent == "openai"` (new choice).
- [ ] Add `--repair-agent` choice: `none`, `opencode`, `openai`.
- [ ] `OpenCodeRepairAdapter` remains functional for existing users.

### 3.4 — Dependency

Add `openai` (or `@ai-sdk/openai`) to `pyproject.toml` dependencies.

---

## Phase 4 — GitHub Transport Layer

**Goal:** Support `GITHUB_TRANSPORT=auto|mcp|cli` with probe-based transport selection and MCP availability caching.

### 4.1 — `env.py` (or `github_client.py`)

Add `GITHUB_TRANSPORT` env var support:
- `auto` (default): probe MCP first, fall back to `gh` CLI, error if neither available.
- `mcp`: require MCP; error if unavailable.
- `cli`: require `gh` CLI; error if unavailable.

### 4.2 — `github_client.py` — Transport abstraction

Refactor `GitHubWriteClient` and `GitHubIssueClient` to select transport at instantiation:

- `MCPTransport`: use MCP protocol (server-sent events or JSON-RPC over stdio). Probe via a lightweight MCP "ping" tool call.
- `GHCLITransport`: wrap `gh api` calls (already implemented as `_via_gh` methods).
- `HTTPTransport`: direct REST API calls (already implemented as `_via_http` methods).

`auto` mode:
1. Try to list MCP tools (call a known MCP endpoint or probe via `python -c "import mcp"` — exact mechanism TBD). Cache result per-run.
2. If MCP unavailable, try `gh api --help` to confirm `gh` CLI is present.
3. If neither, raise an error.

The selected transport is stored on the client instance and used for all subsequent calls.

### 4.3 — `publish_executor.py` / `publishing.py`

If MCP is the active transport, use MCP tools for `create_draft_pull_request`, `create_issue_comment`, etc., instead of `gh` CLI or HTTP.

---

## Phase 5 — Retry Mechanism

**Goal:** Manual retry via `repair issue --retry-from <run-id>`. Up to 3 attempts before `escalated` status.

### 5.1 — `coordinator.py` — `RepairIssueParams`

Add field:
```python
retry_from: str | None = None
```

### 5.2 — `cli.py` — `_repair_issue` argument parsing

Add `--retry-from <run-id>` argument.

### 5.3 — `coordinator.py` — Attempt counter

In `RunCoordinator.repair_issue`:
- [ ] If `params.retry_from` is set, load that run's record from the store.
- [ ] Increment an attempt counter on the run record (stored in `run-record.json` or a separate `attempt-count.txt`).
- [ ] If attempt count > 3, set `RepairResult.status = "escalated"` and skip the repair loop. Governance returns `blocked` with reason code `escalated_after_retries`.
- [ ] The retry is always manual — triggered by CLI call, not automatic.

### 5.4 — `models.py`

Add `"escalated"` to `RepairResult.status` Literal:
```python
status: Literal["not_configured", "blocked", "failed_infra", "completed", "escalated"]
```

---

## Phase 6 — Integration Test Updates

**Goal:** Update existing tests to reflect the new governance model (no provisional).

### 6.1 — `test_pipeline_approved.py`

- [ ] Verify that a run with `qa_passed` produces `approved` verdict and quality `"green"`.

### 6.2 — `test_pipeline_blocked.py`

- [ ] Verify that a run with `qa_failed` produces `blocked` verdict and quality `"degraded"`.

### 6.3 — `test_pipeline_provisional.py`

- [ ] Rename to `test_pipeline_quality_tag.py`.
- [ ] Update assertions: no more `provisional` verdict; check `quality="improved"` instead.

### 6.4 — `test_github_publishing.py`

- [ ] If any test checks for `provisional` in publish plan body, update accordingly.

### 6.5 — `docs/project-status-report.md`

Update pytest count to reflect all 27 integration tests.

---

## Phase 7 — ADRs

**Goal:** Document the two irreversible decisions.

### 7.1 — `docs/adr/`

Create:
- `adr-001-governance-two-verdicts.md`: Why `provisional` was removed; quality tag as informational only; trade-offs.
- `adr-002-llm-abstraction.md`: Why Vercel AI SDK / direct API; no opencode binary dependency; trade-offs.

---

## Open Questions (not resolved in this plan)

| # | Question | Owner |
|---|---|---|
| 1 | What exactly constitutes an MCP probe in `auto` mode? A lightweight tool list call? | TBD |
| 2 | What happens at attempt 4 — same as blocked? Is there a different exit code? | TBD |
| 3 | `side_issues` field on `RepairResult` — store as `tuple[str, ...]` of titles (body/labels in publish plan), or store structured dicts? | TBD |
| 4 | Does the coordinator need to parse `side_issues` from the adapter JSON, or does it flow through via the store? | TBD |
| 5 | `docs-fix-prompt.txt` filename — keep as-is or rename conceptually? (Filename in code can stay; conceptual rename is in CONTEXT.md) | TBD |
| 6 | `GITHUB_TRANSPORT=mcp` — how to error gracefully if MCP tools are not available at runtime? | TBD |

---

## Dependency Order

```
Phase 1 (governance collapse)
  └─ Phase 6 (test updates)
  └─ Phase 7 (ADRs)

Phase 2 (schema + side issues)
  └─ Phase 1 must be done first (RepairResult model change)
  └─ Phase 6 must be updated for side_issues

Phase 3 (LLM adapter)
  └─ Phase 2 must be done first (schema file needed)

Phase 4 (GitHub transport)
  └─ Independent of phases 1-3

Phase 5 (retry mechanism)
  └─ Phase 1 should be done first (escalated status added to model)
```