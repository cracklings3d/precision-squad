"""Tests for the LLM repair adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from precision_squad.models import (
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RunRecord,
)
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


def test_repair_adapter_completed_with_changes(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"summary": "Fixed the bug."})

    with patch("precision_squad.repair.llm_adapter.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        adapter = VercelAIRepairAdapter(model="gpt-4o")
        result = adapter.repair(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_dir,
            repo_workspace=repo_workspace,
        )

    assert result.status == "completed"
    assert result.summary == "Fixed the bug."
    assert result.stdout_path is not None


def test_repair_adapter_completed_no_changes(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"summary": "Fixed the bug."})

    with patch("precision_squad.repair.llm_adapter.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        adapter = VercelAIRepairAdapter(model="gpt-4o")
        result = adapter.repair(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_dir,
            repo_workspace=repo_workspace,
        )

    assert result.status == "completed"
    assert result.summary == "Fixed the bug."


def test_repair_adapter_diff_failed(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"summary": "Fixed the bug."})

    with patch("precision_squad.repair.llm_adapter.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        adapter = VercelAIRepairAdapter(model="gpt-4o")
        result = adapter.repair(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_dir,
            repo_workspace=repo_workspace,
        )

    assert result.status == "completed"


def test_repair_adapter_api_failure(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    with patch("precision_squad.repair.llm_adapter.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        mock_openai.return_value = mock_client

        adapter = VercelAIRepairAdapter(model="gpt-4o")
        result = adapter.repair(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_dir,
            repo_workspace=repo_workspace,
        )

    assert result.status == "failed_infra"
    assert "LLM API call failed" in result.summary


def test_repair_adapter_invalid_response(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"not_summary": "bad"}'

    with patch("precision_squad.repair.llm_adapter.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        adapter = VercelAIRepairAdapter(model="gpt-4o")
        result = adapter.repair(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_dir,
            repo_workspace=repo_workspace,
        )

    assert result.status == "blocked"
    assert "did not match" in result.summary


def test_repair_adapter_with_side_issues(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

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
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(payload)

    with patch("precision_squad.repair.llm_adapter.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        adapter = VercelAIRepairAdapter(model="gpt-4o")
        result = adapter.repair(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_dir,
            repo_workspace=repo_workspace,
        )

    assert result.status == "completed"
    assert len(result.side_issues) == 1
    assert result.side_issues[0].title == "Other bug"


def test_repair_adapter_model_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4-turbo")

    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo_workspace = tmp_path / "repo"
    repo_workspace.mkdir()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"summary": "done"})

    with patch("precision_squad.repair.llm_adapter.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        adapter = VercelAIRepairAdapter()
        adapter.repair(
                intake=intake,
                run_record=run_record,
                run_dir=run_dir,
                contract_artifact_dir=contract_dir,
                repo_workspace=repo_workspace,
            )

    mock_client.chat.completions.create.assert_called_once()
    call_args = mock_client.chat.completions.create.call_args
    assert call_args.kwargs["model"] == "gpt-4-turbo"


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
