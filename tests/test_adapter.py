"""Tests for repair adapter JSON parsing, side issue extraction, and prompt construction."""

from __future__ import annotations

import json
from pathlib import Path

from precision_squad.models import (
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RunRecord,
)
from precision_squad.repair.adapter import (
    _build_repair_prompt,
    _extract_json_events,
    _extract_side_issues,
    _parse_repair_json,
)

# ---------------------------------------------------------------------------
# _extract_json_events
# ---------------------------------------------------------------------------


def test_extract_json_events_from_ndjson() -> None:
    stdout = '{"event": "start"}\n{"event": "end", "summary": "done"}\n'
    events = _extract_json_events(stdout)
    assert len(events) == 2
    assert events[0]["event"] == "start"
    assert events[1]["event"] == "end"


def test_extract_json_events_skips_non_json_lines() -> None:
    stdout = "some log line\n{invalid json\n{\"valid\": true}\n"
    events = _extract_json_events(stdout)
    assert len(events) == 1
    assert events[0] == {"valid": True}


def test_extract_json_events_empty_stdout() -> None:
    assert _extract_json_events("") == []


def test_extract_json_events_no_dicts() -> None:
    stdout = '"just a string"\n123\n[1, 2, 3]\n'
    assert _extract_json_events(stdout) == []


# ---------------------------------------------------------------------------
# _parse_repair_json
# ---------------------------------------------------------------------------


def test_parse_repair_json_valid_summary_only() -> None:
    stdout = json.dumps({"summary": "Fixed the bug."})
    result = _parse_repair_json(stdout)
    assert result is not None
    assert result["summary"] == "Fixed the bug."


def test_parse_repair_json_valid_with_side_issues() -> None:
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
    stdout = json.dumps(payload)
    result = _parse_repair_json(stdout)
    assert result is not None
    assert len(result["side_issues"]) == 1


def test_parse_repair_json_empty_stdout() -> None:
    assert _parse_repair_json("") is None


def test_parse_repair_json_no_json_events() -> None:
    assert _parse_repair_json("just some log output\n") is None


def test_parse_repair_json_last_event_not_dict_skipped() -> None:
    stdout = '{"summary": "first"}\n"not a dict"\n'
    result = _parse_repair_json(stdout)
    # _extract_json_events filters non-dicts, so last event is the dict
    assert result is not None
    assert result["summary"] == "first"


def test_parse_repair_json_missing_summary() -> None:
    stdout = json.dumps({"side_issues": []})
    assert _parse_repair_json(stdout) is None


def test_parse_repair_json_summary_wrong_type() -> None:
    stdout = json.dumps({"summary": 123})
    assert _parse_repair_json(stdout) is None


def test_parse_repair_json_uses_last_event() -> None:
    stdout = (
        json.dumps({"summary": "first", "extra": 1}) + "\n"
        + json.dumps({"summary": "second", "extra": 2}) + "\n"
    )
    result = _parse_repair_json(stdout)
    assert result is not None
    assert result["summary"] == "second"
    assert result["extra"] == 2


def test_parse_repair_json_side_issues_wrong_type() -> None:
    stdout = json.dumps({"summary": "done", "side_issues": "not a list"})
    assert _parse_repair_json(stdout) is None


def test_parse_repair_json_side_issue_missing_required_fields() -> None:
    stdout = json.dumps({
        "summary": "done",
        "side_issues": [{"title": "Only title"}],
    })
    assert _parse_repair_json(stdout) is None


def test_parse_repair_json_side_issue_wrong_field_types() -> None:
    stdout = json.dumps({
        "summary": "done",
        "side_issues": [{"title": 123, "summary": "ok", "body": "ok"}],
    })
    assert _parse_repair_json(stdout) is None


# ---------------------------------------------------------------------------
# _extract_side_issues
# ---------------------------------------------------------------------------


def test_extract_side_issues_valid() -> None:
    data = {
        "summary": "done",
        "side_issues": [
            {
                "title": "Bug A",
                "summary": "Found bug A",
                "body": "Full details",
                "labels": ["bug", "p1"],
            }
        ],
    }
    issues = _extract_side_issues(data)
    assert len(issues) == 1
    assert issues[0].title == "Bug A"
    assert issues[0].summary == "Found bug A"
    assert issues[0].body == "Full details"
    assert issues[0].labels == ("bug", "p1")


def test_extract_side_issues_no_key() -> None:
    assert _extract_side_issues({"summary": "done"}) == ()


def test_extract_side_issues_not_a_list() -> None:
    assert _extract_side_issues({"summary": "done", "side_issues": "bad"}) == ()


def test_extract_side_issues_item_not_dict() -> None:
    data = {"summary": "done", "side_issues": ["not a dict", 42]}
    assert _extract_side_issues(data) == ()


def test_extract_side_issues_missing_title() -> None:
    data = {
        "summary": "done",
        "side_issues": [{"summary": "s", "body": "b"}],
    }
    assert _extract_side_issues(data) == ()


def test_extract_side_issues_missing_summary() -> None:
    data = {
        "summary": "done",
        "side_issues": [{"title": "t", "body": "b"}],
    }
    assert _extract_side_issues(data) == ()


def test_extract_side_issues_title_not_string() -> None:
    data = {
        "summary": "done",
        "side_issues": [{"title": 123, "summary": "s", "body": "b"}],
    }
    assert _extract_side_issues(data) == ()


def test_extract_side_issues_summary_not_string() -> None:
    data = {
        "summary": "done",
        "side_issues": [{"title": "t", "summary": 456, "body": "b"}],
    }
    assert _extract_side_issues(data) == ()


def test_extract_side_issues_missing_body_defaults_empty() -> None:
    data = {
        "summary": "done",
        "side_issues": [{"title": "t", "summary": "s"}],
    }
    issues = _extract_side_issues(data)
    assert len(issues) == 1
    assert issues[0].body == ""


def test_extract_side_issues_labels_not_list() -> None:
    data = {
        "summary": "done",
        "side_issues": [{"title": "t", "summary": "s", "body": "b", "labels": "bad"}],
    }
    issues = _extract_side_issues(data)
    assert len(issues) == 1
    assert issues[0].labels == ()


def test_extract_side_issues_labels_non_string_items_filtered() -> None:
    data = {
        "summary": "done",
        "side_issues": [
            {"title": "t", "summary": "s", "body": "b", "labels": ["good", 123, "also-good"]}
        ],
    }
    issues = _extract_side_issues(data)
    assert len(issues) == 1
    assert issues[0].labels == ("good", "also-good")


def test_extract_side_issues_no_labels_defaults_empty() -> None:
    data = {
        "summary": "done",
        "side_issues": [{"title": "t", "summary": "s", "body": "b"}],
    }
    issues = _extract_side_issues(data)
    assert len(issues) == 1
    assert issues[0].labels == ()


def test_extract_side_issues_mixed_valid_and_invalid() -> None:
    data = {
        "summary": "done",
        "side_issues": [
            {"title": "valid", "summary": "ok", "body": "ok"},
            "not a dict",
            {"title": "missing summary"},
            {"title": "also valid", "summary": "also ok", "body": "also ok"},
        ],
    }
    issues = _extract_side_issues(data)
    assert len(issues) == 2
    assert issues[0].title == "valid"
    assert issues[1].title == "also valid"


# ---------------------------------------------------------------------------
# _build_repair_prompt
# ---------------------------------------------------------------------------


def _make_intake(*, body: str = "Fix the bug.", labels: tuple[str, ...] = ()) -> IssueIntake:
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Test issue",
            body=body,
            labels=labels,
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


def test_build_repair_prompt_non_docs_no_docs_fix_prompt(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    prompt = _build_repair_prompt(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=tmp_path,
        qa_feedback=None,
    )

    assert "Modify code" in prompt
    assert "Output a single JSON object" in prompt
    assert '"summary"' in prompt
    assert "Recommend surfacing" not in prompt


def test_build_repair_prompt_non_docs_with_docs_fix_prompt(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    (contract_dir / "docs-fix-prompt.txt").write_text("Fix the README.", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    prompt = _build_repair_prompt(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=tmp_path,
        qa_feedback=None,
    )

    assert "Modify code" in prompt
    assert "Recommend surfacing them as separate GitHub issues" in prompt
    assert "Fix the README." in prompt


def test_build_repair_prompt_docs_remediation_inlines_fix_prompt(tmp_path: Path) -> None:
    intake = _make_intake(
        body="<!-- precision-squad:docs-remediation -->\nFix the docs.",
        labels=(),
    )
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    (contract_dir / "docs-fix-prompt.txt").write_text("Inline this content.", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    prompt = _build_repair_prompt(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=tmp_path,
        qa_feedback=None,
    )

    assert "Update repository documentation" in prompt
    assert "Inline this content." in prompt
    assert "Recommend surfacing" not in prompt


def test_build_repair_prompt_includes_json_schema(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    prompt = _build_repair_prompt(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=tmp_path,
        qa_feedback=None,
    )

    assert "$schema" in prompt
    assert "summary" in prompt
    assert "side_issues" in prompt


def test_build_repair_prompt_appends_qa_feedback(tmp_path: Path) -> None:
    intake = _make_intake()
    run_record = _make_run_record()
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    prompt = _build_repair_prompt(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=tmp_path,
        qa_feedback="Tests failed: test_foo",
    )

    assert "QA feedback from the previous attempt:" in prompt
    assert "Tests failed: test_foo" in prompt
