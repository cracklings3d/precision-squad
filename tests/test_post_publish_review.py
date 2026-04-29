"""Tests for post-publish PR review behavior."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from precision_squad.models import (
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RunRecord,
)
from precision_squad.post_publish_review import (
    OpenCodePrReviewAgent,
    ReviewAgentResult,
    ReviewRunner,
    _parse_review_output,
    run_post_publish_review,
)


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


def _record(tmp_path: Path) -> RunRecord:
    return RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-27T00:00:00Z",
        updated_at="2026-04-27T00:00:00Z",
        run_dir=str(tmp_path / "run-123"),
    )


def test_run_post_publish_review_reopens_issue_on_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubAgent:
        def __init__(self, result: ReviewAgentResult) -> None:
            self._result = result

        def review(self, **kwargs) -> ReviewAgentResult:
            del kwargs
            return self._result

    actions: list[str] = []

    class StubWriter:
        def get_pull_request_head_sha(self, owner: str, repo: str, pull_number: int):
            del owner, repo, pull_number
            return "head-sha"

        def create_issue_comment(self, reference, body):
            del reference
            actions.append(body)
            return "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9#issuecomment-2"

        def reopen_issue(self, reference):
            del reference
            actions.append("reopened")

    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )

    result = run_post_publish_review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
        reviewer=cast(
            ReviewRunner,
            StubAgent(
            ReviewAgentResult(
                role="reviewer",
                status="rejected",
                summary="Reviewer found an issue.",
                feedback=("Fix the CLI import behavior.",),
            )
            ),
        ),
        architect=cast(
            ReviewRunner,
            StubAgent(
            ReviewAgentResult(
                role="architect",
                status="approved",
                summary="Structure looks fine.",
            )
            ),
        ),
    )

    assert result.status == "rejected"
    assert result.issue_reopened is True
    assert result.issue_comment_url is not None
    assert result.pull_head_sha == "head-sha"
    assert any("Precision Squad Review Feedback" in action for action in actions)
    assert "reopened" in actions


def test_run_post_publish_review_approves_when_both_agents_pass(tmp_path: Path) -> None:
    class StubAgent:
        def __init__(self, result: ReviewAgentResult) -> None:
            self._result = result

        def review(self, **kwargs) -> ReviewAgentResult:
            del kwargs
            return self._result

    class StubWriter:
        def get_pull_request_head_sha(self, owner: str, repo: str, pull_number: int):
            del owner, repo, pull_number
            return "head-sha"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    try:
        result = run_post_publish_review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
        reviewer=cast(
            ReviewRunner,
            StubAgent(
            ReviewAgentResult(
                role="reviewer",
                status="approved",
                summary="Reviewer approves.",
            )
            ),
        ),
        architect=cast(
            ReviewRunner,
            StubAgent(
            ReviewAgentResult(
                role="architect",
                status="approved",
                summary="Architect approves.",
            )
            ),
        ),
        )
    finally:
        monkeypatch.undo()

    assert result.status == "approved"
    assert result.pull_number == 13
    assert result.pull_head_sha == "head-sha"


def test_opencode_pr_review_agent_resolves_custom_provider_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CUSTOM_OPENAI_MODEL_NAME", "MiniMax-M2.7-highspeed")
    commands: list[list[str]] = []

    def fake_run(command, cwd, capture_output, text):
        del cwd, capture_output, text
        commands.append(command)

        class _Completed:
            returncode = 0
            stdout = (
                '{"type":"text","part":{"text":"{\\"status\\":\\"approved\\",'
                '\\"summary\\":\\"ok\\",\\"feedback\\":[]}"}}\n'
            )
            stderr = ""

        return _Completed()

    monkeypatch.setattr("precision_squad.post_publish_review.subprocess.run", fake_run)

    result = OpenCodePrReviewAgent(role="reviewer", model="custom-openai-model").review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
    )

    assert result.status == "approved"
    assert commands[0][8:10] == ["--model", "custom-openai-model/MiniMax-M2.7-highspeed"]


def test_opencode_pr_review_agent_uses_full_configured_model_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CUSTOM_OPENAI_MODEL_NAME", "minimax-cn-coding-plan/MiniMax-M2.7-highspeed")
    commands: list[list[str]] = []

    def fake_run(command, cwd, capture_output, text):
        del cwd, capture_output, text
        commands.append(command)

        class _Completed:
            returncode = 0
            stdout = (
                '{"type":"text","part":{"text":"{\\"status\\":\\"approved\\",'
                '\\"summary\\":\\"ok\\",\\"feedback\\":[]}"}}\n'
            )
            stderr = ""

        return _Completed()

    monkeypatch.setattr("precision_squad.post_publish_review.subprocess.run", fake_run)

    result = OpenCodePrReviewAgent(role="reviewer", model="custom-openai-model").review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
    )

    assert result.status == "approved"
    assert commands[0][8:10] == ["--model", "minimax-cn-coding-plan/MiniMax-M2.7-highspeed"]


def test_opencode_pr_review_agent_accepts_structured_verdict_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command, cwd, capture_output, text):
        del command, cwd, capture_output, text

        class _Completed:
            returncode = 1
            stdout = (
                '{"type":"text","part":{"text":"{\\"status\\":\\"rejected\\",'
                '\\"summary\\":\\"needs follow-up\\",\\"feedback\\":[\\"fix review handling\\"]}"}}\n'
            )
            stderr = "tool exited non-zero"

        return _Completed()

    monkeypatch.setattr("precision_squad.post_publish_review.subprocess.run", fake_run)

    result = OpenCodePrReviewAgent(role="architect").review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
    )

    assert result.status == "rejected"
    assert result.summary == "needs follow-up"
    assert result.feedback == ("fix review handling",)


def test_parse_review_output_accepts_prose_before_json() -> None:
    payload = _parse_review_output(
        [
            {
                "type": "text",
                "part": {
                    "text": (
                        "The implementation is solid. One issue remains.\n\n"
                        '{"status":"rejected","summary":"test is brittle",'
                        '"feedback":["use __version__ in the assertion"]}'
                    )
                },
            }
        ]
    )

    assert payload is not None
    assert payload["status"] == "rejected"
    assert payload["summary"] == "test is brittle"
