"""Tests for the docs-first executor and repair/QA pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from precision_squad.executor import DocsFirstExecutor
from precision_squad.models import (
    ExecutionResult,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RepairResult,
    RunRecord,
)
from precision_squad.repair import (
    OpenCodeRepairAdapter,
    RepairStage,
    WorkspaceQaVerifier,
    _failure_signature,
    _finalize_qa_result,
    evaluate_docs_remediation_validation,
    merge_docs_remediation_execution_result,
    merge_execution_result,
)
from precision_squad.models import ApprovedPlan


def _intake() -> IssueIntake:
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )


def _record(run_dir: Path) -> RunRecord:
    return RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-26T00:00:00Z",
        updated_at="2026-04-26T00:00:00Z",
        run_dir=str(run_dir),
    )


def _write_readme(repo_path: Path, content: str) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "README.md").write_text(content, encoding="utf-8")


def _write_contract(contract_dir: Path, setup_commands: list[str], qa_command: str | None) -> None:
    contract_dir.mkdir(parents=True, exist_ok=True)
    (contract_dir / "contract.json").write_text(
        json.dumps(
            {
                "source_path": "README.md",
                "setup_commands": setup_commands,
                "qa_command": qa_command,
                "notes": [],
                "questions": [],
                "violations": [],
                "findings": [],
            }
        ),
        encoding="utf-8",
    )


def test_executor_requires_existing_repo_path(tmp_path: Path) -> None:
    executor = DocsFirstExecutor(repo_path=tmp_path / "missing-repo")

    result = executor.execute(_intake(), _record(tmp_path / "run"), tmp_path / "run")

    assert result.status == "failed_infra"
    assert result.detail_codes == ("target_repo_missing",)


def test_executor_requires_readme_for_contract_extraction(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "missing_docs"
    assert result.detail_codes == ("docs_missing",)
    assert "newcomer" in result.summary.lower()
    prompt_path = run_dir / "execution-contract" / "docs-fix-prompt.txt"
    assert prompt_path.exists()
    prompt_text = prompt_path.read_text(encoding="utf-8").lower()
    assert "policy violations:" in prompt_text
    assert "docs_entrypoint_present" in prompt_text


def test_executor_extracts_setup_and_qa_contract_from_readme(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _write_readme(
        repo_path,
        "# Example\n\n## Installation\n`python -m pip install -e .[dev]`\n\n## Tests\n`python -m pytest tests/test_cli.py`\n",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "completed"
    assert result.executor_name == "docs"
    contract_payload = json.loads((run_dir / "execution-contract" / "contract.json").read_text(encoding="utf-8"))
    assert contract_payload["setup_commands"] == ["python -m pip install -e .[dev]"]
    assert contract_payload["qa_command"] == "python -m pytest tests/test_cli.py"
    assert contract_payload["violations"] == []
    assert contract_payload["findings"] == []


def test_executor_reports_missing_setup_command_constructively(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _write_readme(repo_path, "# Example\n\n## Tests\n`python -m pytest tests/test_cli.py`\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "missing_docs"
    assert "docs_setup_command_missing" in result.detail_codes
    assert "which package manager should i use" in result.summary.lower()


def test_executor_reports_missing_qa_command_constructively(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _write_readme(repo_path, "# Example\n\n## Installation\n`python -m pip install -e .[dev]`\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "missing_docs"
    assert "docs_qa_command_missing" in result.detail_codes
    assert "what exact command should i run" in result.summary.lower()
    prompt_path = run_dir / "execution-contract" / "docs-fix-prompt.txt"
    assert prompt_path.exists()
    prompt_text = prompt_path.read_text(encoding="utf-8").lower()
    assert "docs_qa_command_present" in prompt_text
    assert "what exact qa command should a newcomer run after making a change?" in prompt_text
    contract_payload = json.loads((run_dir / "execution-contract" / "contract.json").read_text(encoding="utf-8"))
    assert "docs_qa_command_present" in contract_payload["violations"]


def test_executor_reports_ambiguous_docs_when_sources_conflict(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _write_readme(
        repo_path,
        "# Example\n\n## Installation\n`python -m pip install -e .[dev]`\n\n## Tests\n`python -m pytest tests/test_cli.py`\n",
    )
    (repo_path / "CONTRIBUTING.md").write_text(
        "# Contributing\n\n## Setup\n`uv sync`\n\n## Testing\n`python -m pytest tests/test_cli.py`\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "ambiguous_docs"
    assert result.detail_codes == ("docs_ambiguous",)
    assert "multiple competing setup paths" in result.summary.lower()
    prompt_path = run_dir / "execution-contract" / "docs-fix-prompt.txt"
    assert prompt_path.exists()
    assert "remove ambiguity" in prompt_path.read_text(encoding="utf-8").lower()
    contract_payload = json.loads((run_dir / "execution-contract" / "contract.json").read_text(encoding="utf-8"))
    assert "docs_setup_command_unambiguous" in contract_payload["violations"]


def test_executor_blocks_manual_prerequisite_guidance_without_exact_command(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _write_readme(
        repo_path,
        "# Example\n\n"
        "## Development setup\n"
        "`python -m venv .venv`\n"
        "`python -m pip install -e \".[dev]\"`\n\n"
        "## Requirements\n"
        "GTK3 runtime is required on Windows. Download it from https://github.com/example/runtime/releases and run the installer.\n\n"
        "## Testing\n"
        "`python -m pytest`\n",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "missing_docs"
    assert result.detail_codes == ("docs_setup_prerequisites_ambiguous",)
    assert "human-readable prerequisites or environment assumptions" in result.summary.lower()
    contract_payload = json.loads((run_dir / "execution-contract" / "contract.json").read_text(encoding="utf-8"))
    assert "docs_setup_prerequisite_manual_only" in contract_payload["violations"]
    assert "docs_setup_prerequisite_version_pinned" in contract_payload["violations"]
    assert "docs_setup_prerequisite_source_unambiguous" in contract_payload["violations"]
    assert "docs_setup_prerequisite_verification_present" in contract_payload["violations"]
    assert contract_payload["manual_prerequisites"]
    assert contract_payload["verification_gaps"]
    assert {
        finding["rule_id"] for finding in contract_payload["findings"]
    } >= {
        "docs_setup_prerequisite_manual_only",
        "docs_setup_prerequisite_version_pinned",
        "docs_setup_prerequisite_source_unambiguous",
        "docs_setup_prerequisite_verification_present",
    }
    prompt_text = (run_dir / "execution-contract" / "docs-fix-prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "Do not use ambiguous wording such as `latest`" in prompt_text
    assert "include an exact post-install verification command" in prompt_text


def test_executor_accepts_exact_prerequisite_command_with_explicit_assumptions(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _write_readme(
        repo_path,
        "# Example\n\n"
        "## Development setup\n"
        "`python -m venv .venv`\n"
        "`python -m pip install -e \".[dev]\"`\n\n"
        "## Windows System Dependencies\n"
        "GTK3 runtime is required on Windows. Use the release artifact package via Windows Package Manager.\n"
        "```powershell\n"
        "winget install Gtk3.Runtime\n"
        "python -c \"import ctypes; ctypes.CDLL('libgobject-2.0-0')\"\n"
        "```\n"
        "**Environment assumptions**: GTK3 DLLs must be on the system PATH. Open a new PowerShell session before verification so the active shell sees the PATH change.\n\n"
        "## Testing\n"
        "`python -m pytest`\n",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    contract_payload = json.loads((run_dir / "execution-contract" / "contract.json").read_text(encoding="utf-8"))
    assert result.status == "completed"
    assert "docs_setup_prerequisite_manual_only" not in contract_payload["violations"]
    assert "docs_setup_prerequisite_verification_present" not in contract_payload["violations"]
    assert "docs_environment_assumptions_explicit" not in contract_payload["violations"]


def test_executor_blocks_hidden_environment_assumptions(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _write_readme(
        repo_path,
        "# Example\n\n"
        "## Development setup\n"
        "`python -m venv .venv`\n"
        "`python -m pip install -e \".[dev]\"`\n\n"
        "## Windows System Dependencies\n"
        "After installing the runtime, restart your terminal so PATH and DLL discovery update.\n\n"
        "## Testing\n"
        "`python -m pytest`\n",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "missing_docs"
    assert result.detail_codes == ("docs_setup_prerequisites_ambiguous",)
    contract_payload = json.loads((run_dir / "execution-contract" / "contract.json").read_text(encoding="utf-8"))
    assert "docs_environment_assumptions_explicit" in contract_payload["violations"]
    assert "docs_environment_mutation_verification_present" in contract_payload["violations"]
    assert contract_payload["environment_assumptions"]
    assert {
        finding["rule_id"] for finding in contract_payload["findings"]
    } >= {
        "docs_environment_assumptions_explicit",
        "docs_environment_mutation_verification_present",
    }


def test_executor_accepts_explicit_environment_assumptions_with_verification(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _write_readme(
        repo_path,
        "# Example\n\n"
        "## Development setup\n"
        "`python -m venv .venv`\n"
        "`python -m pip install -e \".[dev]\"`\n\n"
        "## Windows System Dependencies\n"
        "If a previous install changed PATH, open a new PowerShell session before running tests.\n"
        "**Environment assumptions**: The active shell must include the updated PATH values before Python imports native libraries. A new PowerShell session is required because the current session does not automatically pick up machine-level PATH changes.\n"
        "```powershell\n"
        "python -c \"import os; print('PATH_OK' if os.environ.get('PATH') else 'PATH_MISSING')\"\n"
        "```\n\n"
        "## Testing\n"
        "`python -m pytest`\n",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    contract_payload = json.loads((run_dir / "execution-contract" / "contract.json").read_text(encoding="utf-8"))
    assert result.status == "completed"
    assert "docs_environment_assumptions_explicit" not in contract_payload["violations"]
    assert "docs_environment_mutation_verification_present" not in contract_payload["violations"]
    assert contract_payload["environment_assumptions"]


def test_executor_normalizes_gtk_runtime_subject_stably_across_aliases(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _write_readme(
        repo_path,
        "# Example\n\n"
        "## Development setup\n"
        "`python -m venv .venv`\n"
        "`python -m pip install -e \".[dev]\"`\n\n"
        "## Windows System Dependencies\n"
        "GTK3 runtime is required on Windows. If `libgobject-2.0-0` is missing, restart your terminal after installation.\n\n"
        "## Testing\n"
        "`python -m pytest`\n",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    contract_payload = json.loads((run_dir / "execution-contract" / "contract.json").read_text(encoding="utf-8"))
    gtk_findings = [
        finding for finding in contract_payload["findings"] if finding["rule_id"].startswith("docs_")
    ]

    assert gtk_findings
    assert {finding["subject_key"] for finding in gtk_findings} == {"gtk3-runtime"}


def test_repair_stage_reports_not_configured_when_command_missing(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    contract_dir.mkdir(parents=True)
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Repair the issue.",
                "implementation_steps": ["Apply minimal change"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    result = RepairStage(repo_path=repo_path, adapter=None).execute(
        _intake(),
        _record(run_dir),
        run_dir,
        contract_dir,
    )

    assert result.status == "not_configured"
    assert "repair_stage_not_configured" in result.detail_codes


def _approved_plan() -> ApprovedPlan:
    return ApprovedPlan(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        plan_summary="Repair the issue.",
        implementation_steps=("Apply minimal change",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )


def test_repair_stage_clears_existing_workspace_before_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    contract_dir.mkdir(parents=True)
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Repair the issue.",
                "implementation_steps": ["Apply minimal change"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    stale_repo_workspace = run_dir / "repair-workspace" / "repo"
    stale_repo_workspace.mkdir(parents=True)
    (stale_repo_workspace / "stale.txt").write_text("stale", encoding="utf-8")

    def fake_run(command, cwd, capture_output, text):
        del cwd, capture_output, text

        class _Completed:
            def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return _Completed(0, "abc123\n")
        if command[:2] == ["git", "clone"]:
            assert not stale_repo_workspace.exists()
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
            return _Completed(0)
        if command[:3] == ["git", "reset", "--hard"]:
            return _Completed(0)
        raise AssertionError(f"Unexpected command: {command}")

    class DummyAdapter:
        def repair(self, **kwargs):
            del kwargs
            return RepairResult(
                status="completed",
                summary="Repair stage completed and produced source changes.",
                detail_codes=("repair_stage_completed",),
                workspace_path=str(run_dir / "repair-workspace"),
                patch_path=str(run_dir / "repair.patch"),
            )

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    result = RepairStage(
        repo_path=repo_path,
        adapter=cast(OpenCodeRepairAdapter, DummyAdapter()),
    ).execute(
        _intake(),
        _record(run_dir),
        run_dir,
        contract_dir,
    )

    assert result.status == "completed"


def test_repair_stage_fails_before_workspace_side_effects_when_approved_plan_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    contract_dir.mkdir(parents=True)

    def fail_if_git_runs(*args, **kwargs):
        raise AssertionError("git commands should not run before approved-plan validation")

    class DummyAdapter:
        def repair(self, **kwargs):
            raise AssertionError("adapter should not run before approved-plan validation")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fail_if_git_runs)

    result = RepairStage(
        repo_path=repo_path,
        adapter=cast(OpenCodeRepairAdapter, DummyAdapter()),
    ).execute(_intake(), _record(run_dir), run_dir, contract_dir)

    assert result.status == "failed_infra"
    assert "approved plan" in result.summary.lower()
    assert "repair_approved_plan_invalid" in result.detail_codes


def test_repair_stage_fails_before_workspace_side_effects_when_approved_plan_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    contract_dir.mkdir(parents=True)
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Repair the issue.",
                "implementation_steps": [1],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    def fail_if_git_runs(*args, **kwargs):
        raise AssertionError("git commands should not run before approved-plan validation")

    class DummyAdapter:
        def repair(self, **kwargs):
            raise AssertionError("adapter should not run before approved-plan validation")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fail_if_git_runs)

    result = RepairStage(
        repo_path=repo_path,
        adapter=cast(OpenCodeRepairAdapter, DummyAdapter()),
    ).execute(_intake(), _record(run_dir), run_dir, contract_dir)

    assert result.status == "failed_infra"
    assert "approved plan" in result.summary.lower()
    assert "repair_approved_plan_invalid" in result.detail_codes


def test_repair_stage_with_no_adapter_still_fails_when_approved_plan_missing(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    contract_dir.mkdir(parents=True)

    result = RepairStage(repo_path=repo_path, adapter=None).execute(
        _intake(),
        _record(run_dir),
        run_dir,
        contract_dir,
    )

    assert result.status == "failed_infra"
    assert "approved plan" in result.summary.lower()
    assert "repair_approved_plan_invalid" in result.detail_codes


def test_repair_stage_with_no_adapter_still_fails_when_approved_plan_invalid(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    contract_dir.mkdir(parents=True)
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Repair the issue.",
                "implementation_steps": ["Apply minimal change"],
                "named_references": [],
                "retrieval_surface_summary": None,
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    result = RepairStage(repo_path=repo_path, adapter=None).execute(
        _intake(),
        _record(run_dir),
        run_dir,
        contract_dir,
    )

    assert result.status == "failed_infra"
    assert "approved plan" in result.summary.lower()
    assert "repair_approved_plan_invalid" in result.detail_codes


def test_opencode_repair_adapter_reports_no_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/test_cli.py")

    commands: list[list[str]] = []

    def fake_run(command, cwd, capture_output, text):
        del cwd, capture_output, text
        commands.append(command)

        class _Completed:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[:2] == ["opencode", "run"]:
            return _Completed(0, '{"type":"text","part":{"text":"done"}}\n')
        if command[:3] == ["git", "diff", "--binary"]:
            return _Completed(0, "")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    result = OpenCodeRepairAdapter().repair(
        approved_plan=_approved_plan(),
        intake=_intake(),
        run_record=_record(run_dir),
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
    )

    assert result.status == "blocked"
    assert "repair_produced_no_changes" in result.detail_codes
    assert any(command[:2] == ["opencode", "run"] for command in commands)


def test_opencode_repair_adapter_prompt_references_issue_context_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "issue.md").write_text(
        "# Issue\n\n## Issue Comments\n\n### Comment 1\nUse exact version output.\n",
        encoding="utf-8",
    )
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/test_cli.py")

    seen_prompt: dict[str, str] = {}

    def fake_run(command, cwd, capture_output, text):
        del cwd, capture_output, text

        class _Completed:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[:2] == ["opencode", "run"]:
            seen_prompt["value"] = command[-1]
            return _Completed(0, '{"type":"text","part":{"text":"done"}}\n')
        if command[:3] == ["git", "diff", "--binary"]:
            return _Completed(0, "")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    OpenCodeRepairAdapter().repair(
        approved_plan=_approved_plan(),
        intake=_intake(),
        run_record=_record(run_dir),
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
    )

    assert str(run_dir / "issue.md") in seen_prompt["value"]


def test_opencode_repair_adapter_resolves_custom_provider_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CUSTOM_OPENAI_MODEL_NAME", "MiniMax-M2.7-highspeed")
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/test_cli.py")
    commands: list[list[str]] = []

    def fake_run(command, cwd, capture_output, text):
        del cwd, capture_output, text
        commands.append(command)

        class _Completed:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[:2] == ["opencode", "run"]:
            return _Completed(0, '{"type":"text","part":{"text":"done"}}\n')
        if command[:3] == ["git", "diff", "--binary"]:
            return _Completed(0, "")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    OpenCodeRepairAdapter(model="custom-openai-model").repair(
        approved_plan=_approved_plan(),
        intake=_intake(),
        run_record=_record(run_dir),
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
    )

    model_index = commands[0].index("--model")
    assert commands[0][model_index : model_index + 2] == [
        "--model",
        "custom-openai-model/MiniMax-M2.7-highspeed",
    ]


def test_opencode_repair_adapter_uses_env_default_model_when_unspecified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CUSTOM_OPENAI_MODEL_NAME", "minimax-cn-coding-plan/MiniMax-M2.7-highspeed")
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/test_cli.py")
    commands: list[list[str]] = []

    def fake_run(command, cwd, capture_output, text):
        del cwd, capture_output, text
        commands.append(command)

        class _Completed:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[:2] == ["opencode", "run"]:
            return _Completed(0, '{"type":"text","part":{"text":"done"}}\n')
        if command[:3] == ["git", "diff", "--binary"]:
            return _Completed(0, "")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    OpenCodeRepairAdapter().repair(
        approved_plan=_approved_plan(),
        intake=_intake(),
        run_record=_record(run_dir),
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
    )

    model_index = commands[0].index("--model")
    assert commands[0][model_index : model_index + 2] == [
        "--model",
        "minimax-cn-coding-plan/MiniMax-M2.7-highspeed",
    ]


def test_opencode_repair_adapter_uses_docs_remediation_prompt_for_docs_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "issue.md").write_text(
        "# Issue\n\nFix docs only.\n",
        encoding="utf-8",
    )
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/test_cli.py")
    (contract_dir / "docs-fix-prompt.txt").write_text("Update README only.\n", encoding="utf-8")

    seen_prompt: dict[str, str] = {}

    def fake_run(command, cwd, capture_output, text):
        del cwd, capture_output, text

        class _Completed:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[:2] == ["opencode", "run"]:
            seen_prompt["value"] = command[-1]
            return _Completed(0, '{"type":"text","part":{"text":"done"}}\n')
        if command[:3] == ["git", "diff", "--binary"]:
            return _Completed(0, "")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    OpenCodeRepairAdapter().repair(
        approved_plan=ApprovedPlan(
            issue_ref="cracklings3d/markdown-pdf-renderer#16",
            plan_summary="Fix docs.",
            implementation_steps=("Update README",),
            named_references=(),
            retrieval_surface_summary="docs/",
            approved=True,
        ),
        intake=IssueIntake(
            issue=GitHubIssue(
                reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
                title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
                body=(
                    "<!-- precision-squad:docs-remediation -->\n"
                    "<!-- precision-squad:target-findings:[{\"rule_id\":\"docs_setup_prerequisite_manual_only\",\"section_key\":\"windows-system-dependencies\",\"source_path\":\"readme.md\",\"subject_key\":\"gtk3-runtime\"},{\"rule_id\":\"docs_setup_prerequisite_source_unambiguous\",\"section_key\":\"windows-system-dependencies\",\"source_path\":\"readme.md\",\"subject_key\":\"gtk3-runtime\"},{\"rule_id\":\"docs_environment_assumptions_explicit\",\"section_key\":\"windows-system-dependencies\",\"source_path\":\"readme.md\",\"subject_key\":\"gtk3-runtime\"}] -->\n\n## Context"
                ),
                labels=(),
                html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
            ),
            summary="Clarify deterministic setup and QA",
            problem_statement="Fix docs.",
            assessment=IssueAssessment(status="runnable", reason_codes=()),
        ),
        run_record=_record(run_dir),
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
    )

    assert "Treat this as a docs-remediation issue" in seen_prompt["value"]
    assert "Update README only" in seen_prompt["value"]
    assert "Eliminate every tracked target finding" in seen_prompt["value"]
    assert "include at least one exact executable acquisition or install command" in seen_prompt["value"]
    assert "explicitly label the canonical source as one of: `release artifact`, `package manager`, or `source build`" in seen_prompt["value"]
    assert "include a literal `Environment assumptions:` line" in seen_prompt["value"]
    assert "include a literal `Environment assumptions:` line" in seen_prompt["value"]


def test_merge_execution_result_promotes_completed_repair(tmp_path: Path) -> None:
    execution_result = ExecutionResult(
        status="completed",
        executor_name="docs",
        summary="Documented execution contract ready.",
        detail_codes=("docs_contract_ready",),
        artifact_dir=str(tmp_path / "artifact"),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair stage completed and produced source changes.",
        detail_codes=("repair_stage_completed",),
        patch_path=str(tmp_path / "repair.patch"),
    )
    from precision_squad.models import QaResult

    qa_result = QaResult(
        status="passed",
        summary="Documented QA command passed in the repair workspace.",
        detail_codes=("qa_passed",),
    )

    merged = merge_execution_result(execution_result, repair_result, qa_result)

    assert merged.status == "completed"
    assert merged.executor_name == "docs+repair"
    assert "repair_stage_completed" in merged.detail_codes
    assert "qa_passed" in merged.detail_codes


def test_merge_docs_remediation_execution_result_promotes_completed_repair(
    tmp_path: Path,
) -> None:
    execution_result = ExecutionResult(
        status="missing_docs",
        executor_name="docs",
        summary="Missing documented QA command.",
        detail_codes=("docs_qa_command_missing",),
        artifact_dir=str(tmp_path / "artifact"),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair stage completed and produced source changes.",
        detail_codes=("repair_stage_completed",),
        patch_path=str(tmp_path / "repair.patch"),
    )
    validation_result = ExecutionResult(
        status="completed",
        executor_name="docs",
        summary="Repository documentation yielded an explicit local setup and QA contract.",
        detail_codes=("docs_contract_ready",),
        artifact_dir=str(tmp_path / "revalidated-artifact"),
        stdout_path=str(tmp_path / "revalidated.stdout.log"),
        stderr_path=str(tmp_path / "revalidated.stderr.log"),
    )

    merged = merge_docs_remediation_execution_result(
        execution_result,
        repair_result,
        validation_result,
    )

    assert merged.status == "completed"
    assert merged.executor_name == "docs+repair"
    assert "docs_remediation_issue" in merged.detail_codes
    assert "repair_stage_completed" in merged.detail_codes
    assert "docs_contract_ready" in merged.detail_codes
    assert merged.artifact_dir == str(tmp_path / "revalidated-artifact")


def test_merge_docs_remediation_execution_result_blocks_when_revalidation_still_fails(
    tmp_path: Path,
) -> None:
    execution_result = ExecutionResult(
        status="missing_docs",
        executor_name="docs",
        summary="Missing documented QA command.",
        detail_codes=("docs_qa_command_missing",),
        artifact_dir=str(tmp_path / "artifact"),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair stage completed and produced source changes.",
        detail_codes=("repair_stage_completed",),
        patch_path=str(tmp_path / "repair.patch"),
    )
    validation_result = ExecutionResult(
        status="missing_docs",
        executor_name="docs",
        summary="Still missing deterministic setup guidance.",
        detail_codes=("docs_setup_prerequisites_ambiguous",),
        artifact_dir=str(tmp_path / "revalidated-artifact"),
    )

    merged = merge_docs_remediation_execution_result(
        execution_result,
        repair_result,
        validation_result,
    )

    assert merged.status == "missing_docs"
    assert merged.summary == "Still missing deterministic setup guidance."
    assert "docs_setup_prerequisites_ambiguous" in merged.detail_codes


def test_evaluate_docs_remediation_validation_allows_baseline_only_findings(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "execution-contract"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "contract.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "rule_id": "docs_qa_command_missing",
                        "source_path": "readme.md",
                        "section_key": "testing",
                        "subject_key": "qa-command",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body=(
                "<!-- precision-squad:docs-remediation -->\n"
                "<!-- precision-squad:target-findings:[{\"rule_id\":\"docs_setup_prerequisite_version_pinned\",\"section_key\":\"windows-system-dependencies\",\"source_path\":\"readme.md\",\"subject_key\":\"gtk3-runtime\"}] -->\n"
                "<!-- precision-squad:baseline-findings:[{\"rule_id\":\"docs_qa_command_missing\",\"section_key\":\"testing\",\"source_path\":\"readme.md\",\"subject_key\":\"qa-command\"}] -->"
            ),
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Clarify deterministic setup and QA",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    validation_result = ExecutionResult(
        status="missing_docs",
        executor_name="docs",
        summary="Still missing docs.",
        detail_codes=("docs_qa_command_missing",),
        artifact_dir=str(artifact_dir),
    )

    scoped_result, scoped_summary = evaluate_docs_remediation_validation(
        intake=intake,
        validation_result=validation_result,
    )

    assert scoped_result.status == "completed"
    assert scoped_summary is not None
    assert "Remaining docs blockers are baseline findings already tracked elsewhere" in scoped_summary


def test_evaluate_docs_remediation_validation_blocks_new_findings(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "execution-contract"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "contract.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "rule_id": "docs_environment_assumptions_explicit",
                        "source_path": "readme.md",
                        "section_key": "windows-system-dependencies",
                        "subject_key": "environment-mutation",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body=(
                "<!-- precision-squad:docs-remediation -->\n"
                "<!-- precision-squad:target-findings:[{\"rule_id\":\"docs_setup_prerequisite_version_pinned\",\"section_key\":\"windows-system-dependencies\",\"source_path\":\"readme.md\",\"subject_key\":\"gtk3-runtime\"}] -->"
            ),
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Clarify deterministic setup and QA",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    validation_result = ExecutionResult(
        status="missing_docs",
        executor_name="docs",
        summary="Still missing docs.",
        detail_codes=("docs_environment_assumptions_explicit",),
        artifact_dir=str(artifact_dir),
    )

    scoped_result, scoped_summary = evaluate_docs_remediation_validation(
        intake=intake,
        validation_result=validation_result,
    )

    assert scoped_result.status == "missing_docs"
    assert scoped_summary is not None
    assert "new untracked docs blockers were introduced or surfaced" in scoped_summary


def test_workspace_qa_verifier_runs_documented_setup_and_qa_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    _write_contract(
        contract_dir,
        ["python -m pip install -e .[dev]"],
        "python -m pytest tests/test_cli.py",
    )
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)

    commands: list[list[str]] = []

    def fake_run(command, cwd, env, capture_output, text):
        del cwd, env, capture_output, text
        commands.append(command)

        class _Completed:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[:4] == ["pwsh", "-NoLogo", "-NoProfile", "-Command"]:
            return _Completed(0, "ok")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    verifier = WorkspaceQaVerifier()
    result = verifier.verify(
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
        iteration=1,
    )

    assert result.status == "passed"
    assert result.command == "python -m pytest tests/test_cli.py"
    assert commands[0][4] == "python -m pip install -e .[dev]"
    assert commands[1][4] == "python -m pytest tests/test_cli.py"


def test_workspace_qa_verifier_bootstraps_whitelisted_uv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "uv run pytest tests/")
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)

    commands: list[list[str]] = []

    def fake_run(command, cwd, env, capture_output, text):
        del cwd, env, capture_output, text
        commands.append(command)

        class _Completed:
            def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[4] == "uv --version":
            return _Completed(1, stderr="missing")
        if command[4] == "python -m pip install uv":
            return _Completed(0, stdout="installed")
        if command[4] in {"python -m pip install -e .[dev]", "uv run pytest tests/"}:
            return _Completed(0, stdout="ok")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    result = WorkspaceQaVerifier().verify(
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
        iteration=1,
    )

    assert result.status == "passed"
    assert any(command[4] == "python -m pip install uv" for command in commands)


def test_workspace_qa_verifier_reports_environment_setup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/test_cli.py")
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)

    def fake_run(command, cwd, env, capture_output, text):
        del cwd, env, capture_output, text

        class _Completed:
            returncode = 1
            stdout = "install failed"
            stderr = "dependency error"

        assert command[4] == "python -m pip install -e .[dev]"
        return _Completed()

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    result = WorkspaceQaVerifier().verify(
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
        iteration=1,
    )

    assert result.status == "failed_infra"
    assert result.command == "python -m pytest tests/test_cli.py"
    assert "qa_environment_setup_failed" in result.detail_codes


def test_workspace_qa_verifier_marks_unrunnable_pytest_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/missing.py")
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)

    def fake_run(command, cwd, env, capture_output, text):
        del cwd, env, capture_output, text

        class _Completed:
            def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[4] == "python -m pip install -e .[dev]":
            return _Completed(0, stdout="installed")
        if command[4] == "python -m pytest tests/missing.py":
            return _Completed(1, stderr="ERROR: file or directory not found: tests/missing.py")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    result = WorkspaceQaVerifier().verify(
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
        iteration=1,
    )

    assert result.status == "unrunnable"
    assert result.detail_codes == ("qa_command_unrunnable",)


def test_workspace_qa_verifier_marks_real_pytest_failures_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/test_cli.py")
    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)

    def fake_run(command, cwd, env, capture_output, text):
        del cwd, env, capture_output, text

        class _Completed:
            def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[4] == "python -m pip install -e .[dev]":
            return _Completed(0, stdout="installed")
        if command[4] == "python -m pytest tests/test_cli.py":
            return _Completed(1, stdout="=================== FAILURES ===================\nFAILED tests/test_cli.py::test_x")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("precision_squad.repair.subprocess.run", fake_run)

    result = WorkspaceQaVerifier().verify(
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
        iteration=1,
    )

    assert result.status == "failed"
    assert result.detail_codes == ("qa_failed",)


def test_finalize_qa_result_accepts_strict_baseline_improvement(tmp_path: Path) -> None:
    baseline_stdout = tmp_path / "baseline.stdout.log"
    baseline_stdout.write_text(
        "ERROR tests/test_renderer.py\n"
        "E   OSError: cannot load library 'libgobject-2.0-0'\n"
        "ERROR tests/test_headers_footers.py\n"
        "E   ModuleNotFoundError: No module named 'markdown_pdf_renderer.styles.styles'\n",
        encoding="utf-8",
    )
    final_stdout = tmp_path / "final.stdout.log"
    final_stdout.write_text(
        "ERROR tests/test_headers_footers.py\n"
        "E   ModuleNotFoundError: No module named 'markdown_pdf_renderer.styles.styles'\n",
        encoding="utf-8",
    )

    baseline = __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
        status="failed",
        summary="baseline failed",
        detail_codes=("qa_failed",),
        command="python -m pytest tests/",
        stdout_path=str(baseline_stdout),
        phase="baseline",
    )
    repaired = __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
        status="failed",
        summary="repaired still failed",
        detail_codes=("qa_failed",),
        command="python -m pytest tests/",
        stdout_path=str(final_stdout),
    )

    result = _finalize_qa_result(
        qa_result=repaired,
        baseline_result=baseline,
        baseline_failure_signature=_failure_signature(baseline),
    )

    assert result.status == "failed"
    assert result.phase == "final"
    assert result.quality == "improved"
    assert "qa_baseline_improved" not in result.detail_codes


def test_parse_repair_json_extracts_summary() -> None:
    from precision_squad.repair.adapter import _parse_repair_json

    stdout = '{"type":"text","part":{"text":"done"}}\n{"summary":"Fixed the issue by updating README"}\n'
    result = _parse_repair_json(stdout)
    assert result is not None
    assert result["summary"] == "Fixed the issue by updating README"


def test_parse_repair_json_returns_none_when_no_summary() -> None:
    from precision_squad.repair.adapter import _parse_repair_json

    stdout = '{"type":"text","part":{"text":"done"}}\n{"other":"field"}\n'
    result = _parse_repair_json(stdout)
    assert result is None


def test_parse_repair_json_returns_none_when_no_json() -> None:
    from precision_squad.repair.adapter import _parse_repair_json

    stdout = '{"type":"text","part":{"text":"done"}}\njust plain text\n'
    result = _parse_repair_json(stdout)
    assert result is None


def test_extract_side_issues_parses_valid_data() -> None:
    from precision_squad.repair.adapter import _extract_side_issues

    repair_json = {
        "summary": "Fixed issue",
        "side_issues": [
            {
                "title": "Missing version pin",
                "summary": "requirements.txt lacks version pin for pytest",
                "body": "Full details about missing version pin...",
                "labels": ["docs", "bug"],
            },
            {
                "title": "CI badge broken",
                "summary": "Travis CI badge returns 404",
                "body": "The Travis CI badge URL has changed",
                "labels": ["ci"],
            },
        ],
    }
    result = _extract_side_issues(repair_json)
    assert len(result) == 2
    assert result[0].title == "Missing version pin"
    assert result[0].summary == "requirements.txt lacks version pin for pytest"
    assert result[0].body == "Full details about missing version pin..."
    assert result[0].labels == ("docs", "bug")
    assert result[1].title == "CI badge broken"
    assert result[1].labels == ("ci",)


def test_extract_side_issues_skips_invalid_items() -> None:
    from precision_squad.repair.adapter import _extract_side_issues

    repair_json = {
        "summary": "Fixed issue",
        "side_issues": [
            {
                "title": "Valid issue",
                "summary": "This is valid",
                "body": "Body",
            },
            {
                "title": "Missing summary field",
                "body": "No summary",
            },
            {
                "not_a_title": "Missing title",
                "summary": "Has summary",
                "body": "Body",
            },
        ],
    }
    result = _extract_side_issues(repair_json)
    assert len(result) == 1
    assert result[0].title == "Valid issue"


def test_extract_side_issues_returns_empty_for_no_side_issues() -> None:
    from precision_squad.repair.adapter import _extract_side_issues

    repair_json = {"summary": "Fixed issue"}
    result = _extract_side_issues(repair_json)
    assert result == ()


def test_extract_side_issues_returns_empty_for_non_list() -> None:
    from precision_squad.repair.adapter import _extract_side_issues

    repair_json = {"summary": "Fixed issue", "side_issues": "not a list"}
    result = _extract_side_issues(repair_json)
    assert result == ()


def test_opencode_repair_adapter_prompt_includes_json_output_instruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from precision_squad.repair.adapter import _build_repair_prompt

    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/test_cli.py")

    prompt = _build_repair_prompt(
        approved_plan=_approved_plan(),
        intake=_intake(),
        run_record=_record(run_dir),
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
        qa_feedback=None,
    )

    assert "Output a single JSON object with at least a `summary` field" in prompt
    assert "side_issues" in prompt
    assert "title" in prompt
    assert "summary" in prompt
    assert "body" in prompt


def test_opencode_repair_adapter_prompt_inlines_docs_fix_prompt_for_docs_remediation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from precision_squad.repair.adapter import _build_repair_prompt

    repo_workspace = tmp_path / "workspace" / "repo"
    repo_workspace.mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "issue.md").write_text(
        "# Issue\n\nFix docs only.\n",
        encoding="utf-8",
    )
    contract_dir = run_dir / "execution-contract"
    _write_contract(contract_dir, ["python -m pip install -e .[dev]"], "python -m pytest tests/test_cli.py")
    docs_fix_content = "Add a setup command to README."
    (contract_dir / "docs-fix-prompt.txt").write_text(docs_fix_content, encoding="utf-8")

    docs_intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body=(
                "<!-- precision-squad:docs-remediation -->\n"
                "<!-- precision-squad:target-findings:[{\"rule_id\":\"docs_setup_command_present\",\"section_key\":\"setup\",\"source_path\":\"readme.md\",\"subject_key\":\"setup-command\"}] -->\n\n"
                "## Context"
            ),
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Fix docs",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    prompt = _build_repair_prompt(
        approved_plan=ApprovedPlan(
            issue_ref="cracklings3d/markdown-pdf-renderer#16",
            plan_summary="Fix docs.",
            implementation_steps=("Update docs",),
            named_references=(),
            retrieval_surface_summary="docs/",
            approved=True,
        ),
        intake=docs_intake,
        run_record=_record(run_dir),
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
        qa_feedback=None,
    )

    assert docs_fix_content in prompt
    assert str(contract_dir / "docs-fix-prompt.txt") not in prompt
