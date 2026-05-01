# ADR-002: LLM Abstraction — Direct API Over Agent Binary

## Status

Accepted

## Date

2026-05-01

## Context

The original repair stage used `OpenSWE` as the execution substrate. The system called an external agent binary (`opencode`) to perform code modifications. This created a hard dependency on a specific binary installation, version, and runtime environment.

The implementation plan (Phase 3) proposed replacing this with a direct LLM API call via the Vercel AI SDK or equivalent.

## Decision

Replace the `opencode` binary dependency with a direct LLM API call using the `openai` Python SDK. Introduce a `RepairAdapter` protocol that abstracts the repair mechanism, allowing multiple implementations:

1. **`OpenCodeRepairAdapter`** — the original binary-based adapter (preserved for backward compatibility)
2. **`VercelAIRepairAdapter`** — direct LLM API adapter using `openai` SDK

The coordinator selects the adapter based on the `--repair-agent` CLI argument (`none`, `opencode`, `vercel-ai`).

## Rationale

### Why Direct LLM API

1. **No binary dependency.** The `openai` SDK is a pure Python package. No shell subprocess, no binary installation, no version pinning on an external tool.

2. **Deterministic API contract.** The OpenAI API has a stable, documented contract. The adapter controls the prompt, the response format, and the error handling. No hidden prompt rewriting or side effects inside an agent binary.

3. **Testability.** The adapter can be tested by mocking the API response. No need to install and configure a binary for unit tests.

4. **Portability.** Works in any Python environment with network access. No platform-specific binary compilation or installation.

5. **Composability.** The adapter can be extended with custom prompt construction, response parsing, and error handling without modifying an external tool.

### Why a Protocol-Based Abstraction

1. **Multiple implementations.** The `RepairAdapter` protocol allows both binary-based and API-based adapters to coexist. Operators can choose the adapter that fits their environment.

2. **Test isolation.** Tests can use a mock adapter that returns controlled results without making API calls or running binaries.

3. **Future extensibility.** New adapters (e.g., Anthropic, local models) can be added by implementing the protocol without changing the orchestration logic.

4. **Clean separation.** The coordinator orchestrates; the adapter repairs. The protocol defines the contract between them.

### Why OpenAI SDK Over Vercel AI SDK

1. **Direct dependency.** The Vercel AI SDK wraps the OpenAI SDK. Using the wrapper adds a dependency without adding value for this use case.

2. **Mature ecosystem.** The OpenAI SDK is well-documented, widely used, and stable.

3. **Simpler dependency tree.** One SDK instead of two.

## Trade-offs

### What We Lost

- **Agent binary capabilities.** The `opencode` binary may have had built-in prompt engineering, tool use, or multi-step reasoning that the direct API call does not replicate. The adapter must implement all prompt construction explicitly.

- **Binary-level error recovery.** The binary may have had retry logic, rate limiting, or error handling that the adapter must now implement.

- **Vercel AI SDK features.** If Vercel AI SDK adds features beyond OpenAI SDK (e.g., streaming, multi-provider routing), we will not automatically benefit from them.

### What We Gained

- **No binary installation.** Pure Python dependency.
- **Full control over prompt and response.** No hidden transformations.
- **Testable without binary.** Mock the API, test the logic.
- **Portable.** Works in any Python environment.
- **Composable.** Custom prompt construction, response parsing, error handling.

## Consequences

- `openai` is a required dependency in `pyproject.toml`.
- `VercelAIRepairAdapter` uses the OpenAI SDK directly, not the Vercel AI SDK.
- The adapter name `VercelAIRepairAdapter` is a historical artifact; the implementation uses OpenAI SDK. (See issue #25 for naming cleanup.)
- The `OpenCodeRepairAdapter` is preserved for backward compatibility but is not the default.
- The `--repair-agent` CLI argument selects the adapter.
- The `RepairAdapter` protocol defines the contract for all adapters.

## Design Notes

### Adapter Protocol

```python
@runtime_checkable
class RepairAdapter(Protocol):
    def repair(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
    ) -> RepairResult: ...

    def with_qa_feedback(self, feedback: str) -> RepairAdapter: ...
```

### Prompt Construction

Both adapters use the same prompt construction logic (`_build_repair_prompt`). The prompt is adapter-agnostic; the adapter is responsible for sending it to the LLM and parsing the response.

### Response Parsing

The adapter parses the LLM response as JSON, validates it against the repair-result schema, and maps it to a `RepairResult`. If parsing fails, the result is `blocked` with appropriate error context.

## References

- [CONTEXT.md](../../CONTEXT.md) — Repair Agent
- [Implementation Plan](../implementation-plan.md) — Phase 3
- [architecture.md](../architecture.md) — Repair Stage section (updated)
- [Issue #4](https://github.com/cracklings3d/precision-squad/issues/4) — LLM Adapter implementation
- [Issue #25](https://github.com/cracklings3d/precision-squad/issues/25) — Naming cleanup
