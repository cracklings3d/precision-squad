"""Tests for the LLM repair adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import precision_squad.repair.llm_adapter as llm_adapter_module
from precision_squad.models import (
    ApprovedPlan,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RunRecord,
)
from precision_squad.repair.llm_adapter import VercelAIRepairAdapter


# ---------------------------------------------------------------------------
# VercelAIRepairAdapter.repair
# ---------------------------------------------------------------------------


def _make_intake() -> IssueIntake:
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Test issue",
            body="Fix the bug.",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Test issue",
        problem_statement="Fix the bug.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )


def _make_run_record() -> RunRecord:
    return RunRecord(
        run_id="run-test",
        issue_ref="owner/repo#1",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-test",
    )


def _approved_plan() -> ApprovedPlan:
    return ApprovedPlan(
        issue_ref="owner/repo#1",
        plan_summary="Repair the issue.",
        implementation_steps=("Apply minimal change",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )


def test_repair_adapter_never_constructs_openai_compatible_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    def fail_if_openai_client_constructed(*args: object, **kwargs: object) -> object:
        pytest.fail("repair() must not construct an OpenAI-compatible client")

    monkeypatch.setattr(
        llm_adapter_module,
        "openai",
        SimpleNamespace(OpenAI=fail_if_openai_client_constructed),
        raising=False,
    )

    adapter = VercelAIRepairAdapter(model="gpt-4o")
    result = adapter.repair(
        approved_plan=_approved_plan(),
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
    )

    assert result.status == "blocked"


def test_repair_adapter_returns_retired_blocked_result_without_openai_client(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    adapter = VercelAIRepairAdapter(model="gpt-4o")
    result = adapter.repair(
        approved_plan=_approved_plan(),
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
    )

    assert result.status == "blocked"
    assert "Direct LLM compatibility path is retired on the current baseline." in result.summary
    assert result.detail_codes == (
        "direct_llm_runtime_retired",
        "repair_workspace_path_missing",
        "repair_patch_path_missing",
        "repair_output_not_applied",
    )
    assert result.patch_path is None
    assert result.workspace_path is None
    assert result.stdout_path is None
    assert not (run_dir / "repair.patch").exists()
    assert not any(run_dir.iterdir())


def test_repair_adapter_retirement_result_does_not_claim_applied_workspace_or_patch(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    adapter = VercelAIRepairAdapter(model="gpt-4o")
    result = adapter.repair(
        approved_plan=_approved_plan(),
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=repo_workspace,
    )

    assert result.status == "blocked"
    assert "no patch artifact was persisted" in result.summary
    assert result.patch_path is None
    assert result.workspace_path is None
    assert result.side_issues == ()
    assert result.design_decisions == ()


def test_repair_adapter_with_qa_feedback(tmp_path: Path) -> None:
    adapter = VercelAIRepairAdapter(model="gpt-4o")
    new_adapter = adapter.with_qa_feedback("Tests failed: test_foo")
    assert new_adapter.qa_feedback == "Tests failed: test_foo"
    assert new_adapter.model == "gpt-4o"
    assert adapter.qa_feedback is None


def test_repair_adapter_protocol_compliance() -> None:
    """Verify VercelAIRepairAdapter satisfies RepairAdapter protocol."""
    from precision_squad.repair.adapter import RepairAdapter

    adapter = VercelAIRepairAdapter()
    assert isinstance(adapter, RepairAdapter)
