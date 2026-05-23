"""Tests for publish plan preparation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad.models import (
    DecisionLogArtifact,
    DesignDecision,
    GitHubIssue,
    GovernanceVerdict,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    PostPublishReviewResult,
    RepairResult,
    RunRecord,
    SideIssue,
)
from precision_squad.publishing import (
    PostReviewAutomationResult,
    RequiredDecisionLogArtifactMissingError,
    apply_post_review_automation,
    build_publish_plan,
)
from precision_squad.run_store import RunStore


def test_build_publish_plan_creates_draft_pr_for_approved() -> None:
    intake = IssueIntake(
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
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    verdict = GovernanceVerdict(
        status="approved",
        summary="QA passed.",
        reason_codes=(),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert plan.status == "draft_pr"
    assert plan.title == "Add --version flag to CLI"


def test_build_publish_plan_includes_design_decisions_from_persisted_artifact(tmp_path: Path) -> None:
    intake = IssueIntake(
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
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=str(run_dir),
    )
    RunStore(tmp_path / "runs").write_decision_log(
        run_dir,
        DecisionLogArtifact(
            attempt=1,
            entries=(
                DesignDecision(
                    sequence=1,
                    summary="Persist in coordinator",
                    rationale="Publishing must read canonical persisted evidence.",
                    plan_steps=("Persist the current attempt's decision log",),
                    named_references=("src/precision_squad/coordinator.py",),
                    affected_targets=("src/precision_squad/coordinator.py",),
                ),
            ),
        ),
    )
    verdict = GovernanceVerdict(
        status="approved",
        summary="QA passed.",
        reason_codes=(),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert "## Design Decisions" in plan.body
    assert "```json" in plan.body
    assert "Persist in coordinator" in plan.body
    assert "canonical persisted evidence" in plan.body


def test_build_publish_plan_omits_design_decisions_when_artifact_empty(tmp_path: Path) -> None:
    intake = IssueIntake(
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
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=str(run_dir),
    )
    RunStore(tmp_path / "runs").write_decision_log(
        run_dir,
        DecisionLogArtifact(attempt=1, entries=()),
    )
    verdict = GovernanceVerdict(
        status="approved",
        summary="QA passed.",
        reason_codes=(),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert "## Design Decisions" not in plan.body


def test_build_publish_plan_fails_when_completed_repair_missing_decision_log_artifact(
    tmp_path: Path,
) -> None:
    intake = IssueIntake(
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
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=str(run_dir),
    )
    verdict = GovernanceVerdict(
        status="approved",
        summary="QA passed.",
        reason_codes=(),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair completed.",
        detail_codes=("repair_stage_completed",),
        workspace_path=str(run_dir / "repair-workspace"),
        patch_path=str(run_dir / "repair.patch"),
    )

    with pytest.raises(
        RequiredDecisionLogArtifactMissingError,
        match="Missing required decision-log artifact",
    ):
        build_publish_plan(intake, run_record, verdict, repair_result)


def test_build_publish_plan_embeds_blocker_fingerprint_for_follow_up_issue() -> None:
    intake = IssueIntake(
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
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    run_dir = Path(run_record.run_dir)
    (run_dir / "execution-contract").mkdir(parents=True, exist_ok=True)
    (run_dir / "execution-contract" / "contract.json").write_text(
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
    verdict = GovernanceVerdict(
        status="blocked",
        summary="Missing documented QA command.",
        reason_codes=("docs_qa_command_missing",),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert plan.status == "follow_up_issue"
    assert "precision-squad:blocker-fingerprint:" in plan.body
    assert "precision-squad:blocker-findings:" in plan.body
    assert "precision-squad:target-findings:" in plan.body
    assert "precision-squad:baseline-findings:" in plan.body
    assert "docs_qa_command_missing" in plan.body


def test_build_publish_plan_uses_specific_contract_findings_for_umbrella_docs_reason() -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 17),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/17",
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#17",
        status="runnable",
        created_at="2026-04-29T00:00:00Z",
        updated_at="2026-04-29T00:00:00Z",
        run_dir=".precision-squad/runs/run-123-specific",
    )
    run_dir = Path(run_record.run_dir)
    (run_dir / "execution-contract").mkdir(parents=True, exist_ok=True)
    (run_dir / "execution-contract" / "contract.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "rule_id": "docs_setup_prerequisite_manual_only",
                        "source_path": "readme.md",
                        "section_key": "windows-system-dependencies",
                        "subject_key": "gtk3-runtime",
                    },
                    {
                        "rule_id": "docs_environment_assumptions_explicit",
                        "source_path": "readme.md",
                        "section_key": "windows-system-dependencies",
                        "subject_key": "gtk3-runtime",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    verdict = GovernanceVerdict(
        status="blocked",
        summary="Prerequisites are ambiguous.",
        reason_codes=("docs_setup_prerequisites_ambiguous",),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert plan.status == "follow_up_issue"
    assert "docs_setup_prerequisite_manual_only" in plan.body
    assert "docs_environment_assumptions_explicit" in plan.body
    assert "docs_setup_prerequisites_ambiguous\"" not in plan.body


def test_build_publish_plan_does_not_recurse_follow_up_issue_for_docs_remediation_issue() -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body="<!-- precision-squad:docs-remediation -->\n\n## Context\nFix docs.",
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#16",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    verdict = GovernanceVerdict(
        status="blocked",
        summary="Missing documented QA command.",
        reason_codes=("docs_qa_command_missing",),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert plan.status == "issue_comment"


def test_build_publish_plan_creates_follow_up_issue_for_side_issues() -> None:
    intake = IssueIntake(
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
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    run_dir = Path(run_record.run_dir)
    verdict = GovernanceVerdict(
        status="blocked",
        summary="QA failed.",
        reason_codes=("qa_failed",),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair completed with side issues.",
        detail_codes=("repair_stage_completed",),
        workspace_path=str(run_dir / "repair-workspace"),
        patch_path=str(run_dir / "repair.patch"),
        side_issues=(
            SideIssue(
                title="Missing version pin",
                summary="requirements.txt lacks version pin for pytest",
                body="Full details here",
                labels=("docs", "bug"),
            ),
            SideIssue(
                title="CI badge broken",
                summary="Travis CI badge returns 404",
                body="The badge URL has changed",
                labels=("ci",),
            ),
        ),
    )

    plan = build_publish_plan(intake, run_record, verdict, repair_result)

    assert plan.status == "follow_up_issue"
    assert "Side issues surfaced" in plan.title
    assert "Missing version pin" in plan.body
    assert "CI badge broken" in plan.body
    assert "`docs`, `bug`" in plan.body
    assert "`ci`" in plan.body
    assert "requirements.txt lacks version pin" in plan.body


def test_build_publish_plan_returns_issue_comment_when_no_side_issues() -> None:
    intake = IssueIntake(
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
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    run_dir = Path(run_record.run_dir)
    verdict = GovernanceVerdict(
        status="blocked",
        summary="QA failed.",
        reason_codes=("qa_failed",),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair completed.",
        detail_codes=("repair_stage_completed",),
        workspace_path=str(run_dir / "repair-workspace"),
        patch_path=str(run_dir / "repair.patch"),
        side_issues=(),
    )

    plan = build_publish_plan(intake, run_record, verdict, repair_result)

    assert plan.status == "issue_comment"


# --- Tests for PostReviewAutomationResult dataclass ---

import pytest
from precision_squad.publishing import PostReviewAutomationResult


def test_post_review_automation_result_success() -> None:
    result = PostReviewAutomationResult(
        status="success",
        summary="All operations completed.",
        operations_completed=("mark_pull_request_ready", "merge_pull_request", "close_issue"),
    )
    assert result.status == "success"
    assert result.summary == "All operations completed."
    assert result.operations_completed == (
        "mark_pull_request_ready",
        "merge_pull_request",
        "close_issue",
    )
    assert result.error is None


def test_post_review_automation_result_skipped() -> None:
    result = PostReviewAutomationResult(
        status="skipped",
        summary="Automation skipped: review was not approved.",
        operations_completed=(),
    )
    assert result.status == "skipped"
    assert result.operations_completed == ()


def test_post_review_automation_result_failed() -> None:
    result = PostReviewAutomationResult(
        status="failed",
        summary="Automation failed: merge conflict.",
        operations_completed=("mark_pull_request_ready",),
        error="Merge conflict detected",
    )
    assert result.status == "failed"
    assert result.error == "Merge conflict detected"


def test_post_review_automation_result_frozen() -> None:
    result = PostReviewAutomationResult(
        status="success",
        summary="Done.",
        operations_completed=("merge_pull_request",),
    )
    with pytest.raises(AttributeError):
        result.status = "failed"  # type: ignore[f_assignment]


# --- Tests for apply_post_review_automation ---


def test_apply_post_review_automation_skipped_when_not_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When approved=False, the function returns a skipped result without doing any GitHub operations."""
    result = apply_post_review_automation(run_id="run-123", approved=False)
    assert result.status == "skipped"
    assert "not approved" in result.summary
    assert result.operations_completed == ()
    assert result.error is None


def test_apply_post_review_automation_full_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When approved=True, all three operations complete successfully."""
    from unittest.mock import MagicMock

    run_id = "run-success-123"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "post-publish-review-result.json").write_text(
        json.dumps(
            {
                "status": "approved",
                "summary": "PR approved by both reviewers.",
                "pull_request_url": "https://github.com/owner/repo/pull/5",
                "pull_number": 5,
                "reviewer_status": "approved",
                "reviewer_summary": "LGTM",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    # Create a mock client with the required methods
    mock_client = MagicMock()

    monkeypatch.setattr(
        "precision_squad.publishing.GitHubWriteClient.from_env",
        lambda token_env: mock_client,
    )
    monkeypatch.setattr(
        "precision_squad.publishing.RunStore.load_run",
        lambda self, run_id: RunRecord(
            run_id=run_id,
            issue_ref="owner/repo#9",
            status="runnable",
            created_at="2026-04-28T00:00:00Z",
            updated_at="2026-04-28T00:00:00Z",
            run_dir=str(run_dir),
        ),
    )

    result = apply_post_review_automation(run_id=run_id, approved=True)

    assert result.status == "success"
    assert result.operations_completed == (
        "mark_pull_request_ready",
        "merge_pull_request",
        "close_issue",
    )
    assert result.error is None
    # Verify the mock client methods were called
    assert mock_client.mark_pull_request_ready.called
    assert mock_client.merge_pull_request.called
    assert mock_client.close_issue.called


def test_apply_post_review_automation_failure_on_merge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When merge fails, operations_completed contains the operations that ran before the failure."""
    from unittest.mock import MagicMock

    run_id = "run-merge-fail-123"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "post-publish-review-result.json").write_text(
        json.dumps(
            {
                "status": "approved",
                "summary": "PR approved.",
                "pull_request_url": "https://github.com/owner/repo/pull/5",
                "pull_number": 5,
                "reviewer_status": "approved",
                "reviewer_summary": "LGTM",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    from precision_squad.github_client import GitHubClientError

    mock_client = MagicMock()
    # make mark_pull_request_ready succeed, merge_pull_request fail
    mock_client.mark_pull_request_ready.return_value = None
    mock_client.merge_pull_request.side_effect = GitHubClientError(
        "Merge failed: branch is out-of-date"
    )

    monkeypatch.setattr(
        "precision_squad.publishing.GitHubWriteClient.from_env",
        lambda token_env: mock_client,
    )
    monkeypatch.setattr(
        "precision_squad.publishing.RunStore.load_run",
        lambda self, run_id: RunRecord(
            run_id=run_id,
            issue_ref="owner/repo#9",
            status="runnable",
            created_at="2026-04-28T00:00:00Z",
            updated_at="2026-04-28T00:00:00Z",
            run_dir=str(run_dir),
        ),
    )

    result = apply_post_review_automation(run_id=run_id, approved=True)

    assert result.status == "failed"
    assert "merge" in result.summary.lower() or "failed" in result.summary.lower()
    assert "mark_pull_request_ready" in result.operations_completed
    assert "merge_pull_request" not in result.operations_completed
    assert "close_issue" not in result.operations_completed
    assert result.error is not None


def test_apply_post_review_automation_failure_on_close_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When close_issue fails, operations_completed contains mark and merge but not close."""
    from unittest.mock import MagicMock

    run_id = "run-close-fail-123"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "post-publish-review-result.json").write_text(
        json.dumps(
            {
                "status": "approved",
                "summary": "PR approved.",
                "pull_request_url": "https://github.com/owner/repo/pull/5",
                "pull_number": 5,
                "reviewer_status": "approved",
                "reviewer_summary": "LGTM",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    from precision_squad.github_client import GitHubClientError

    mock_client = MagicMock()
    # make mark_pull_request_ready and merge_pull_request succeed, close_issue fail
    mock_client.mark_pull_request_ready.return_value = None
    mock_client.merge_pull_request.return_value = None
    mock_client.close_issue.side_effect = GitHubClientError(
        "Issue close failed: state transition not allowed"
    )

    monkeypatch.setattr(
        "precision_squad.publishing.GitHubWriteClient.from_env",
        lambda token_env: mock_client,
    )
    monkeypatch.setattr(
        "precision_squad.publishing.RunStore.load_run",
        lambda self, run_id: RunRecord(
            run_id=run_id,
            issue_ref="owner/repo#9",
            status="runnable",
            created_at="2026-04-28T00:00:00Z",
            updated_at="2026-04-28T00:00:00Z",
            run_dir=str(run_dir),
        ),
    )

    result = apply_post_review_automation(run_id=run_id, approved=True)

    assert result.status == "failed"
    assert "close" in result.summary.lower() or "failed" in result.summary.lower()
    assert "mark_pull_request_ready" in result.operations_completed
    assert "merge_pull_request" in result.operations_completed
    assert "close_issue" not in result.operations_completed
    assert result.error is not None
