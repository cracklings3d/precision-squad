"""Tests for rerun branch reuse in the repair loop."""

from __future__ import annotations

import pytest

from precision_squad.models import GitHubIssue, IssueAssessment, IssueIntake, IssueReference
from precision_squad.repair.orchestration import _resolve_rerun_branch


def test_resolve_rerun_branch_uses_latest_rejected_pull_request(monkeypatch: pytest.MonkeyPatch) -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
            comments=(
                "## Precision Squad Review Feedback\n- PR: https://github.com/cracklings3d/markdown-pdf-renderer/pull/15\n- Reviewer verdict: `rejected`\n",
            ),
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    class StubWriter:
        def get_pull_request_head_branch(self, owner: str, repo: str, pull_number: int) -> str:
            assert owner == "cracklings3d"
            assert repo == "markdown-pdf-renderer"
            assert pull_number == 15
            return "precision-squad/run-20260428-012411-5e87af7f"

    monkeypatch.setattr(
        "precision_squad.repair.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )

    assert _resolve_rerun_branch(intake) == "precision-squad/run-20260428-012411-5e87af7f"
