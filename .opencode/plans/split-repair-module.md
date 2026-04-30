# Refactor: Split `repair.py` Into 3 Modules

## Objective
Split `src/precision_squad/repair.py` (1154 lines) into 3 modules under a `repair/` package for improved depth, locality, and testability. Also fix 4 pyright type errors.

## File Changes

### New Files

1. **`src/precision_squad/repair/__init__.py`**
   - Re-export all public symbols for backward compatibility
   - Re-export private symbols used by tests

2. **`src/precision_squad/repair/adapter.py`**
   - `OpenCodeRepairAdapter` class (lines 33-144)
   - `_build_repair_prompt` (lines 639-720)
   - `_extract_json_events` (lines 824-836)
   - Imports: `json`, `subprocess`, `Path`, `Literal`, `opencode_model`, `docs_remediation`, `intake`, `models`

3. **`src/precision_squad/repair/qa.py`**
   - New `QaFailureClassification` frozen dataclass (replaces raw dict return)
   - `_classify_qa_command_failure` → returns `QaFailureClassification` (fixes pyright)
   - `WorkspaceQaVerifier` class (lines 263-384)
   - `_load_execution_contract` (lines 1043-1057)
   - `_format_qa_log_section` (lines 858-860)
   - `_ensure_whitelisted_tools_available` (lines 1060-1094)
   - `_leading_tool` (lines 1097-1101)
   - `_run_baseline_qa` (lines 863-919)
   - `_finalize_qa_result` (lines 922-957)
   - `_failure_signature` (lines 960-978)
   - `build_qa_feedback` (lines 839-855)
   - Imports: `json`, `os`, `shutil`, `subprocess`, `dataclass`, `Path`, `models`

4. **`src/precision_squad/repair/orchestration.py`**
   - `run_repair_qa_loop` (lines 387-471)
   - `run_docs_remediation_repair` (lines 723-745)
   - `evaluate_docs_remediation_validation` (lines 748-821)
   - `synthesis_artifacts_ready` (lines 474-479)
   - `resolve_artifact_dir` (lines 482-489)
   - `merge_execution_result` (lines 492-554)
   - `merge_docs_remediation_execution_result` (lines 557-636)
   - `_resolve_rerun_branch` (lines 981-993)
   - `_resolve_remote_origin_url` (lines 996-1006)
   - `_reset_workspace_to_rerun_branch` (lines 1009-1041)
   - Imports: `shutil`, `subprocess`, `Path`, `models`, `docs_remediation`, `github_client`, `intake`, `rerun_context`, `.adapter` (OpenCodeRepairAdapter), `.qa` (WorkspaceQaVerifier)

### Deleted Files
- `src/precision_squad/repair.py` (replaced by package)

### Unchanged Files (import from new package via `__init__.py`)
- `src/precision_squad/cli.py` — imports unchanged
- `tests/test_executor.py` — imports unchanged (including private symbol access)
- `tests/test_repair_rerun.py` — imports `_resolve_rerun_branch`

## Implementation Order

1. Create `repair/` directory
2. Write `repair/adapter.py` — extract adapter code
3. Write `repair/qa.py` — extract QA code, add `QaFailureClassification` dataclass
4. Write `repair/orchestration.py` — extract orchestration code
5. Write `repair/__init__.py` — re-exports
6. Delete old `repair.py`
7. Run `pytest` — verify 109 tests still pass
8. Run `pyright` — verify 0 errors
9. Run `ruff check` — verify no new issues

## Type Fix Details

### `_classify_qa_command_failure` (pyright errors at repair.py:371-373)

Replace:
```python
def _classify_qa_command_failure(
    stdout: str, stderr: str, command: str
) -> dict[str, Literal["failed", "unrunnable"] | str | tuple[str, ...]]:
```

With:
```python
@dataclass(frozen=True, slots=True)
class QaFailureClassification:
    status: Literal["failed", "unrunnable"]
    summary: str
    detail_codes: tuple[str, ...]

def _classify_qa_command_failure(
    stdout: str, stderr: str, command: str
) -> QaFailureClassification:
```

Update call site in `WorkspaceQaVerifier.verify()`:
```python
classification = _classify_qa_command_failure(completed.stdout, completed.stderr, command)
return QaResult(
    status=classification.status,
    summary=classification.summary,
    detail_codes=classification.detail_codes,
    ...
)
```

### `_classify_missing_contract_parts` (pyright error at executor.py:166)

The `_DocsBlockResolution` internal dataclass already has proper types. The issue is that the function returns the correct type, but the caller assigns `.status` which is `str` to `ExecutionResult(status=...)` expecting `Literal[...]`. This should be auto-resolved since `_DocsBlockResolution.status` is already `Literal["missing_docs"]`. Verify after refactoring.

## Risk Mitigation
- All 109 existing tests must pass unchanged
- The `__init__.py` must re-export every symbol the tests and CLI import
- Private symbols (`_failure_signature`, `_finalize_qa_result`, `_resolve_rerun_branch`) need re-exports for test access
