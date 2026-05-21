"""Tests for the LLM repair adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from precision_squad.models import (
    ApprovedPlan,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RunRecord,
)
from precision_squad.repair.llm_adapter import VercelAIRepairAdapter
from precision_squad.run_store import RunStore

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


def test_repair_adapter_returns_retired_compatibility_result_without_openai_call(
    tmp_path: Path,
) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    with patch("precision_squad.repair.llm_adapter.openai.OpenAI") as mock_openai:
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
    assert "retired compatibility path" in result.summary
    assert "not an active supported repair mode" in result.summary
    assert result.detail_codes == (
        "repair_workspace_path_missing",
        "repair_patch_path_missing",
        "repair_output_not_applied",
    )
    assert result.patch_path is None
    assert result.stdout_path is not None
    assert not (run_dir / "repair.patch").exists()
    mock_openai.assert_not_called()


def test_repair_adapter_persists_retired_compatibility_summary_without_patch_artifact(
    tmp_path: Path,
) -> None:
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

    RunStore(tmp_path / "runs").write_repair_result(run_dir, result)
    payload = json.loads((run_dir / "repair-result.json").read_text(encoding="utf-8"))

    assert payload["summary"] == result.summary
    assert "retired compatibility path" in payload["summary"]
    assert "not an active supported repair mode" in payload["summary"]
    assert payload["patch_path"] is None
    assert not (run_dir / "repair.patch").exists()


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
