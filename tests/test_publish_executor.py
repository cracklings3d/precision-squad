"""Tests for publish execution behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from precision_squad.models import (
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    PublishPlan,
)
from precision_squad.publish_executor import execute_publish_plan


def _intake() -> IssueIntake:
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 1),
            title="[Plan] Markdown to PDF Renderer",
            body="## Project Plan",
            labels=("plan",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/1",
        ),
        summary="Markdown to PDF Renderer",
        problem_statement="Project plan",
        assessment=IssueAssessment(status="blocked", reason_codes=("issue_marked_as_plan",)),
    )


def test_execute_publish_plan_returns_dry_run_without_publish_flag() -> None:
    result = execute_publish_plan(
        _intake(),
        PublishPlan(
            status="issue_comment",
            title="Blocked: Markdown to PDF Renderer",
            body="Blocked body",
            reason_codes=("issue_marked_as_plan",),
        ),
        publish=False,
    )

    assert result.status == "dry_run"
    assert result.target == "issue_comment"


def test_execute_publish_plan_posts_issue_comment_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubWriter:
        @staticmethod
        def create_issue_comment(reference: IssueReference, body: str) -> str:
            del reference, body
            return (
                "https://github.com/cracklings3d/markdown-pdf-renderer/"
                "issues/1#issuecomment-1"
            )

    monkeypatch.setattr(
        "precision_squad.publish_executor.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": _StubWriter(),
    )

    result = execute_publish_plan(
        _intake(),
        PublishPlan(
            status="issue_comment",
            title="Blocked: Markdown to PDF Renderer",
            body="Blocked body",
            reason_codes=("issue_marked_as_plan",),
        ),
        publish=True,
    )

    assert result.status == "published"
    assert result.url is not None


def test_execute_publish_plan_creates_follow_up_issue_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubWriter:
        @staticmethod
        def find_open_docs_remediation_issue(
            owner: str,
            repo: str,
            *,
            blocker_fingerprint: str,
            blocker_findings: list[dict[str, str]] | None = None,
            exclude_issue_number: int | None = None,
        ) -> tuple[int, str] | None:
            del owner, repo, blocker_fingerprint, blocker_findings, exclude_issue_number
            return None

        @staticmethod
        def create_issue(owner: str, repo: str, *, title: str, body: str) -> str:
            del owner, repo, title, body
            return "https://github.com/cracklings3d/markdown-pdf-renderer/issues/2"

    monkeypatch.setattr(
        "precision_squad.publish_executor.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": _StubWriter(),
    )

    result = execute_publish_plan(
        _intake(),
        PublishPlan(
            status="follow_up_issue",
            title="Docs blocker",
            body=(
                "<!-- precision-squad:docs-remediation -->\n"
                "<!-- precision-squad:blocker-fingerprint:1234567890abcdef -->\n\n"
                "<!-- precision-squad:blocker-findings:[{\"rule_id\":\"docs_qa_command_missing\",\"section_key\":\"testing\",\"source_path\":\"readme.md\",\"subject_key\":\"qa-command\"}] -->\n\n"
                "Blocked body"
            ),
            reason_codes=("docs_qa_command_missing",),
        ),
        publish=True,
    )

    assert result.status == "published"
    assert result.target == "follow_up_issue"
    assert result.url == "https://github.com/cracklings3d/markdown-pdf-renderer/issues/2"
    assert result.summary == "Created follow-up issue for a repo-level blocker."


def test_execute_publish_plan_reuses_existing_follow_up_issue_when_fingerprint_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubWriter:
        @staticmethod
        def find_open_docs_remediation_issue(
            owner: str,
            repo: str,
            *,
            blocker_fingerprint: str,
            blocker_findings: list[dict[str, str]] | None = None,
            exclude_issue_number: int | None = None,
        ) -> tuple[int, str] | None:
            del owner, repo, exclude_issue_number
            assert blocker_fingerprint == "1234567890abcdef"
            assert blocker_findings == [
                {
                    "rule_id": "docs_qa_command_missing",
                    "section_key": "testing",
                    "source_path": "readme.md",
                    "subject_key": "qa-command",
                }
            ]
            return (3, "https://github.com/cracklings3d/markdown-pdf-renderer/issues/3")

        @staticmethod
        def create_issue(owner: str, repo: str, *, title: str, body: str) -> str:
            raise AssertionError("should reuse existing follow-up issue instead of creating one")

    monkeypatch.setattr(
        "precision_squad.publish_executor.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": _StubWriter(),
    )

    result = execute_publish_plan(
        _intake(),
        PublishPlan(
            status="follow_up_issue",
            title="Docs blocker",
            body=(
                "<!-- precision-squad:docs-remediation -->\n"
                "<!-- precision-squad:blocker-fingerprint:1234567890abcdef -->\n\n"
                "<!-- precision-squad:blocker-findings:[{\"rule_id\":\"docs_qa_command_missing\",\"section_key\":\"testing\",\"source_path\":\"readme.md\",\"subject_key\":\"qa-command\"}] -->\n\n"
                "Blocked body"
            ),
            reason_codes=("docs_qa_command_missing",),
        ),
        publish=True,
    )

    assert result.status == "published"
    assert result.target == "follow_up_issue"
    assert result.url == "https://github.com/cracklings3d/markdown-pdf-renderer/issues/3"
    assert result.summary == "Reused existing follow-up issue instead of creating a duplicate."


def test_execute_publish_plan_creates_draft_pr_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class _StubWriter:
        def create_draft_pull_request(self, reference, title, body, head, base="main") -> str:
            del reference, title, body, head, base
            return "https://github.com/cracklings3d/markdown-pdf-renderer/pull/2"

    monkeypatch.setattr(
        "precision_squad.publish_executor.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": _StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.publish_executor._publish_draft_pull_request",
        lambda intake, plan, client, run_dir, token_env: (
            "https://github.com/cracklings3d/markdown-pdf-renderer/pull/2",
            "precision-squad/run-123",
            None,
        ),
    )

    result = execute_publish_plan(
        _intake(),
        PublishPlan(
            status="draft_pr",
            title="Add --version flag to CLI",
            body="PR body",
            reason_codes=(),
        ),
        publish=True,
        run_dir=tmp_path / "run-123",
    )

    assert result.status == "published"
    assert result.target == "draft_pr"
    assert result.url == "https://github.com/cracklings3d/markdown-pdf-renderer/pull/2"


def test_execute_publish_plan_reuses_existing_pull_request_when_plan_targets_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "precision_squad.publish_executor.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": object(),
    )
    monkeypatch.setattr(
        "precision_squad.publish_executor._publish_draft_pull_request",
        lambda intake, plan, client, run_dir, token_env: (
            "https://github.com/cracklings3d/markdown-pdf-renderer/pull/15",
            "precision-squad/run-20260428-012411-5e87af7f",
            15,
        ),
    )

    result = execute_publish_plan(
        _intake(),
        PublishPlan(
            status="draft_pr",
            title="Add --version flag to CLI",
            body="Updated body",
            reason_codes=(),
            pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/15",
            pull_number=15,
        ),
        publish=True,
        run_dir=tmp_path / "run-123",
    )

    assert result.status == "published"
    assert result.url == "https://github.com/cracklings3d/markdown-pdf-renderer/pull/15"
    assert result.pull_number == 15
    assert result.branch_name == "precision-squad/run-20260428-012411-5e87af7f"
    assert result.summary == "Updated existing pull request from the stored repair workspace."


def test_prepare_publish_workspace_strips_generated_artifacts(tmp_path: Path) -> None:
    from precision_squad.publish_executor import _prepare_publish_workspace

    run_dir = tmp_path / "run-123"
    source_repo = run_dir / "repair-workspace" / "repo"
    (source_repo / "src" / "markdown_pdf_renderer.egg-info").mkdir(parents=True)
    (source_repo / "src" / "markdown_pdf_renderer.egg-info" / "PKG-INFO").write_text(
        "generated\n",
        encoding="utf-8",
    )
    (source_repo / "tests" / "__pycache__").mkdir(parents=True)
    (source_repo / "tests" / "__pycache__" / "test_cli.cpython-314.pyc").write_bytes(b"pyc")
    cli_file = source_repo / "src" / "markdown_pdf_renderer" / "cli.py"
    cli_file.parent.mkdir(parents=True, exist_ok=True)
    cli_file.write_text("print('ok')\n", encoding="utf-8")

    publish_repo = _prepare_publish_workspace(run_dir, source_repo)

    assert publish_repo.exists()
    assert not (publish_repo / "src" / "markdown_pdf_renderer.egg-info").exists()
    assert not any(publish_repo.rglob("__pycache__"))
    assert not any(publish_repo.rglob("*.pyc"))
