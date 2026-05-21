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
from precision_squad.run_store import RunStore
from precision_squad.repair.llm_adapter import (
    VercelAIRepairAdapter,
    _parse_llm_response,
)

# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------


def test_parse_llm_response_valid_summary_only() -> None:
    payload = json.dumps({"summary": "Fixed the bug."})
    result = _parse_llm_response(payload)
    assert result is not None
    assert result["summary"] == "Fixed the bug."


def test_parse_llm_response_valid_with_side_issues() -> None:
    payload = {
        "summary": "Fixed the bug.",
        "side_issues": [
            {
                "title": "Other bug",
                "summary": "Found another bug",
                "body": "Details here",
                "labels": ["bug"],
            }
        ],
    }
    result = _parse_llm_response(json.dumps(payload))
    assert result is not None
    assert len(result["side_issues"]) == 1


def test_parse_llm_response_valid_with_design_decisions() -> None:
    payload = {
        "summary": "Fixed the bug.",
        "design_decisions": [
            {
                "sequence": 1,
                "summary": "Persist in coordinator",
                "rationale": "Publish plan must read persisted evidence.",
            }
        ],
    }
    result = _parse_llm_response(json.dumps(payload))
    assert result is not None
    assert len(result["design_decisions"]) == 1


def test_parse_llm_response_empty_string() -> None:
    assert _parse_llm_response("") is None


def test_parse_llm_response_not_json() -> None:
    assert _parse_llm_response("not json") is None


def test_parse_llm_response_not_dict() -> None:
    assert _parse_llm_response('"just a string"') is None


def test_parse_llm_response_missing_summary() -> None:
    assert _parse_llm_response(json.dumps({"side_issues": []})) is None


def test_parse_llm_response_summary_wrong_type() -> None:
    assert _parse_llm_response(json.dumps({"summary": 123})) is None


def test_parse_llm_response_side_issues_wrong_type() -> None:
    assert _parse_llm_response(json.dumps({"summary": "done", "side_issues": "bad"})) is None


def test_parse_llm_response_side_issue_missing_required() -> None:
    payload = json.dumps({"summary": "done", "side_issues": [{"title": "Only title"}]})
    assert _parse_llm_response(payload) is None


def test_parse_llm_response_design_decision_missing_required() -> None:
    payload = json.dumps(
        {"summary": "done", "design_decisions": [{"sequence": 1, "summary": "Only summary"}]}
    )
    assert _parse_llm_response(payload) is None


def test_parse_llm_response_design_decision_rejects_whitespace_summary() -> None:
    payload = json.dumps(
        {
            "summary": "done",
            "design_decisions": [{"sequence": 1, "summary": "   ", "rationale": "Valid rationale"}],
        }
    )
    assert _parse_llm_response(payload) is None


def test_parse_llm_response_design_decision_rejects_whitespace_rationale() -> None:
    payload = json.dumps(
        {
            "summary": "done",
            "design_decisions": [{"sequence": 1, "summary": "Valid summary", "rationale": "\n\t "}],
        }
    )
    assert _parse_llm_response(payload) is None


def test_parse_llm_response_pretty_printed_json() -> None:
    payload = json.dumps({"summary": "Fixed the bug."}, indent=2)
    result = _parse_llm_response(payload)
    assert result is not None
    assert result["summary"] == "Fixed the bug."

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
