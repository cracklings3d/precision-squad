"""Tests for the retry mechanism in RunCoordinator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock

import pytest

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    ApprovedPlan,
    DecisionLogArtifact,
    DesignDecision,
    EvaluationResult,
    ExecutionResult,
    GitHubIssue,
    GovernanceVerdict,
    IssueAssessment,
    IssueDraft,
    IssueDraftProvenance,
    IssueIntake,
    IssueReference,
    IssueReview,
    IssueReviewProvenance,
    PlanReview,
    PlanReviewProvenance,
    PublishResult,
    QaResult,
    RepairResult,
    RunRecord,
    RunRequest,
)
from precision_squad.run_store import RunStore


def _make_intake(*, blocked: bool = False) -> IssueIntake:
    status = "blocked" if blocked else "runnable"
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
        assessment=IssueAssessment(status=status, reason_codes=()),
    )


def _make_params(tmp_path: Path, *, retry_from: str | None = None) -> RepairIssueParams:
    return RepairIssueParams(
        issue_ref="owner/repo#1",
        runs_dir=tmp_path / "runs",
        repo_path=tmp_path / "repo",
        publish=False,
        repair_agent="none",
        repair_model=None,
        review_model=None,
        retry_from=retry_from,
        approved_plan=_approved_plan() if retry_from is None else None,
    )


def _create_previous_run(
    store: RunStore,
    attempt: int = 1,
    *,
    include_approved_plan: bool = True,
) -> RunRecord:
    """Create a previous run record with the specified attempt number."""
    intake = _make_intake()
    request = RunRequest(issue_ref="owner/repo#1", runs_dir=str(store.root))
    record = store.create_run(request, intake)
    # Update the record with the attempt number
    updated = RunRecord(
        run_id=record.run_id,
        issue_ref=record.issue_ref,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        run_dir=record.run_dir,
        attempt=attempt,
    )
    store.write_run_record(updated)
    if include_approved_plan:
        store.write_approved_plan(Path(updated.run_dir), _approved_plan(updated.issue_ref))
    return updated


def _approved_plan(issue_ref: str = "owner/repo#1") -> ApprovedPlan:
    return ApprovedPlan(
        issue_ref=issue_ref,
        plan_summary="Fix the bug with a minimal change.",
        implementation_steps=("Update the implementation",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )


def test_retry_increments_attempt(tmp_path: Path) -> None:
    """Test that retry increments the attempt counter."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=1)

    dependencies = MagicMock()
    dependencies.synthesis_artifacts_ready.return_value = False
    dependencies.run_post_publish_review_if_needed.return_value = None

    coordinator = RunCoordinator()
    params = _make_params(tmp_path, retry_from=previous.run_id)

    # Create a minimal execution result for the mock
    exec_result = ExecutionResult(
        status="completed",
        executor_name="test",
        summary="Test execution",
        detail_codes=(),
    )
    dependencies.execute_publish_plan.return_value = PublishResult(
        status="dry_run",
        target="issue_comment",
        summary="Dry run",
        url=None,
    )

    intake = _make_intake()
    # Mock the executor to return a completed result
    import precision_squad.coordinator as coord_module
    original_execute = coord_module.DocsFirstExecutor.execute

    def mock_execute(self, intake, run_record, run_dir):
        return exec_result

    coord_module.DocsFirstExecutor.execute = mock_execute
    try:
        report = coordinator.repair_issue(
            params=params,
            intake=intake,
            dependencies=dependencies,
        )
    finally:
        coord_module.DocsFirstExecutor.execute = original_execute

    assert report.run_record.attempt == 2


def test_retry_escalated_after_3_attempts(tmp_path: Path) -> None:
    """Test that repair is escalated after 3 failed attempts."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=3)

    dependencies = MagicMock()
    dependencies.execute_publish_plan.return_value = PublishResult(
        status="dry_run",
        target="issue_comment",
        summary="Dry run",
        url=None,
    )

    coordinator = RunCoordinator()
    params = _make_params(tmp_path, retry_from=previous.run_id)
    intake = _make_intake()

    report = coordinator.repair_issue(
        params=params,
        intake=intake,
        dependencies=dependencies,
    )

    assert report.repair_result is not None
    assert report.repair_result.status == "escalated"
    assert "escalated" in report.repair_result.summary
    assert report.exit_code == 4


def test_retry_governance_blocked_after_escalation(tmp_path: Path) -> None:
    """Test that governance returns blocked with escalated reason code."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=3)

    dependencies = MagicMock()
    dependencies.execute_publish_plan.return_value = PublishResult(
        status="dry_run",
        target="issue_comment",
        summary="Dry run",
        url=None,
    )

    coordinator = RunCoordinator()
    params = _make_params(tmp_path, retry_from=previous.run_id)
    intake = _make_intake()

    report = coordinator.repair_issue(
        params=params,
        intake=intake,
        dependencies=dependencies,
    )

    assert report.governance_verdict is not None
    verdict = report.governance_verdict
    assert isinstance(verdict, GovernanceVerdict)
    assert verdict.status == "blocked"
    assert "escalated_after_retries" in verdict.reason_codes


def test_retry_from_nonexistent_run(tmp_path: Path) -> None:
    """Test that retry from non-existent run returns error."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)

    dependencies = MagicMock()
    coordinator = RunCoordinator()
    params = _make_params(tmp_path, retry_from="nonexistent-run-id")
    intake = _make_intake()

    report = coordinator.repair_issue(
        params=params,
        intake=intake,
        dependencies=dependencies,
    )

    assert report.exit_code == 3


def test_retry_from_different_issue_returns_blocked_report(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    other_intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 2),
            title="Other issue",
            body="Fix the other bug.",
            labels=(),
            html_url="https://github.com/owner/repo/issues/2",
        ),
        summary="Other issue",
        problem_statement="Fix the other bug.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    request = RunRequest(issue_ref="Owner/Repo#2", runs_dir=str(store.root))
    previous = store.create_run(request, other_intake)
    store.write_approved_plan(Path(previous.run_dir), _approved_plan("Owner/Repo#2"))

    report = RunCoordinator().repair_issue(
        params=_make_params(tmp_path, retry_from=previous.run_id),
        intake=_make_intake(),
        dependencies=MagicMock(),
    )

    assert report.exit_code == 3
    assert report.run_record.status == "blocked"


def test_retry_attempt_stored_in_run_record(tmp_path: Path) -> None:
    """Test that attempt number is persisted in run record."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=2)

    dependencies = MagicMock()
    dependencies.synthesis_artifacts_ready.return_value = False
    dependencies.execute_publish_plan.return_value = PublishResult(
        status="dry_run",
        target="issue_comment",
        summary="Dry run",
        url=None,
    )
    dependencies.run_post_publish_review_if_needed.return_value = None

    coordinator = RunCoordinator()
    params = _make_params(tmp_path, retry_from=previous.run_id)
    intake = _make_intake()

    import precision_squad.coordinator as coord_module
    exec_result = ExecutionResult(
        status="completed",
        executor_name="test",
        summary="Test execution",
        detail_codes=(),
    )

    original_execute = coord_module.DocsFirstExecutor.execute

    def mock_execute(self, intake, run_record, run_dir):
        return exec_result
    coord_module.DocsFirstExecutor.execute = mock_execute

    try:
        report = coordinator.repair_issue(
            params=params,
            intake=intake,
            dependencies=dependencies,
        )
    finally:
        coord_module.DocsFirstExecutor.execute = original_execute

    # Verify the attempt was persisted
    loaded = store.load_run(report.run_record.run_id)
    assert loaded.attempt == 3


def test_retry_carries_forward_approved_plan_into_new_run_directory(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=1)
    previous_run_dir = Path(previous.run_dir)
    store.write_approved_plan(previous_run_dir, _approved_plan())

    dependencies = MagicMock()
    dependencies.synthesis_artifacts_ready.return_value = False
    dependencies.execute_publish_plan.return_value = PublishResult(
        status="dry_run",
        target="issue_comment",
        summary="Dry run",
        url=None,
    )
    dependencies.run_post_publish_review_if_needed.return_value = None

    coordinator = RunCoordinator()
    params = _make_params(tmp_path, retry_from=previous.run_id)
    intake = _make_intake()

    import precision_squad.coordinator as coord_module

    exec_result = ExecutionResult(
        status="completed",
        executor_name="test",
        summary="Test execution",
        detail_codes=(),
    )
    original_execute = coord_module.DocsFirstExecutor.execute

    def mock_execute(self, intake, run_record, run_dir):
        return exec_result

    coord_module.DocsFirstExecutor.execute = mock_execute
    try:
        report = coordinator.repair_issue(
            params=params,
            intake=intake,
            dependencies=dependencies,
        )
    finally:
        coord_module.DocsFirstExecutor.execute = original_execute

    new_run_dir = Path(report.run_record.run_dir)
    assert (new_run_dir / "approved-plan.json").exists()
    carried_forward = RunStore.load_approved_plan(new_run_dir, issue_ref="owner/repo#1")
    assert carried_forward.issue_ref == "owner/repo#1"
    assert carried_forward.plan_summary == "Fix the bug with a minimal change."
    assert carried_forward.implementation_steps == ("Update the implementation",)


def test_retry_with_unapproved_persisted_plan_fails_before_creating_new_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=1)
    previous_run_dir = Path(previous.run_dir)
    (previous_run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Invalid plan",
                "implementation_steps": ["Step 1"],
                "named_references": [],
                "retrieval_surface_summary": "",
                "approved": False,
            }
        ),
        encoding="utf-8",
    )

    coordinator = RunCoordinator()
    with pytest.raises(ValueError, match="failed structural validation"):
        coordinator.repair_issue(
            params=_make_params(tmp_path, retry_from=previous.run_id),
            intake=_make_intake(),
            dependencies=MagicMock(),
        )

    run_ids = [path.name for path in store.root.iterdir() if path.is_dir()]
    assert run_ids == [previous.run_id]


def test_retry_without_prior_approved_plan_fails_with_missing_artifact_message(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=1, include_approved_plan=False)

    coordinator = RunCoordinator()
    with pytest.raises(ValueError, match="missing prior approved-plan.json"):
        coordinator.repair_issue(
            params=_make_params(tmp_path, retry_from=previous.run_id),
            intake=_make_intake(),
            dependencies=MagicMock(),
        )

    run_ids = [path.name for path in store.root.iterdir() if path.is_dir()]
    assert run_ids == [previous.run_id]


def test_retry_with_invalid_prior_approved_plan_fails_with_validation_message(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=1)
    previous_run_dir = Path(previous.run_dir)
    (previous_run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Plan",
                "implementation_steps": ["   "],
                "named_references": [],
                "retrieval_surface_summary": "",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    coordinator = RunCoordinator()
    with pytest.raises(ValueError, match="failed structural validation"):
        coordinator.repair_issue(
            params=_make_params(tmp_path, retry_from=previous.run_id),
            intake=_make_intake(),
            dependencies=MagicMock(),
        )

    run_ids = [path.name for path in store.root.iterdir() if path.is_dir()]
    assert run_ids == [previous.run_id]


def test_retry_escalated_uses_correct_attempt_count(tmp_path: Path) -> None:
    """Test that escalated result uses the correct attempt count."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=3)

    dependencies = MagicMock()
    dependencies.execute_publish_plan.return_value = PublishResult(
        status="dry_run",
        target="issue_comment",
        summary="Dry run",
        url=None,
    )

    coordinator = RunCoordinator()
    params = _make_params(tmp_path, retry_from=previous.run_id)
    intake = _make_intake()

    report = coordinator.repair_issue(
        params=params,
        intake=intake,
        dependencies=dependencies,
    )

    assert report.repair_result is not None
    # Attempt 4 > 3, so should be escalated
    assert "4" in report.repair_result.summary or "3" in report.repair_result.summary


def test_retry_escalation_persists_approved_plan_into_new_run_directory(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    previous = _create_previous_run(store, attempt=3)

    dependencies = MagicMock()
    dependencies.execute_publish_plan.return_value = PublishResult(
        status="dry_run",
        target="issue_comment",
        summary="Dry run",
        url=None,
    )

    coordinator = RunCoordinator()
    report = coordinator.repair_issue(
        params=_make_params(tmp_path, retry_from=previous.run_id),
        intake=_make_intake(),
        dependencies=dependencies,
    )

    escalated_run_dir = Path(report.run_record.run_dir)
    assert (escalated_run_dir / "approved-plan.json").exists()

    persisted_plan = RunStore.load_approved_plan(escalated_run_dir, issue_ref="owner/repo#1")
    assert persisted_plan == _approved_plan()


# ---------------------------------------------------------------------------
# Helpers for publish/resume preflight tests
# ---------------------------------------------------------------------------


def _make_issue_review_approved(run_id: str, issue_ref: str) -> IssueReview:
    return IssueReview(
        run_id=run_id,
        issue_ref=issue_ref,
        review_status="approved",
        summary="Issue review approved",
        feedback=(),
        provenance=IssueReviewProvenance(
            source_artifact="issue-draft.json",
            run_id=run_id,
            issue_ref=issue_ref,
        ),
    )


def _make_plan_review_approved(run_id: str, issue_ref: str) -> PlanReview:
    return PlanReview(
        run_id=run_id,
        issue_ref=issue_ref,
        review_status="approved",
        summary="Plan review approved",
        feedback=(),
        provenance=PlanReviewProvenance(
            source_artifact="approved-plan.json",
            run_id=run_id,
            issue_ref=issue_ref,
        ),
    )


def _make_issue_draft(issue_ref: str) -> IssueDraft:
    return IssueDraft(
        owner="owner",
        repo="repo",
        number=1,
        issue_ref=issue_ref,
        issue_url=f"https://github.com/{issue_ref.replace('#', '/issues/')}",
        title="Test issue",
        summary="Test issue summary",
        problem_statement="Fix the bug.",
        labels=(),
        intake_status="runnable",
        intake_reason_codes=(),
        provenance=IssueDraftProvenance(
            source_artifacts=("issue-intake.json",),
            requested_issue_ref=issue_ref,
        ),
    )


def _create_publish_resume_source_run(
    store: RunStore,
    attempt: int = 1,
    *,
    include_issue_draft: bool = True,
    include_issue_review: bool = True,
    issue_review_approved: bool = True,
    include_approved_plan: bool = True,
    include_plan_review: bool = True,
    plan_review_approved: bool = True,
) -> tuple[RunStore, RunRecord]:
    """Create a source run suitable for publish resume testing.

    Creates a run with all implement-stage artifacts. Individual artifacts
    can be excluded or modified via parameters.
    """
    intake = _make_intake()
    issue_ref = "owner/repo#1"
    request = RunRequest(issue_ref=issue_ref, runs_dir=str(store.root))
    record = store.create_run(request, intake)

    updated = RunRecord(
        run_id=record.run_id,
        issue_ref=record.issue_ref,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        run_dir=record.run_dir,
        attempt=attempt,
    )
    store.write_run_record(updated)
    run_dir = Path(updated.run_dir)

    # create_run() always writes issue-draft.json, so remove it if not included
    if not include_issue_draft:
        (run_dir / "issue-draft.json").unlink(missing_ok=True)

    # Write issue-draft.json directly
    if include_issue_draft:
        draft = _make_issue_draft(issue_ref)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "issue-draft.json").write_text(
            json.dumps(
                {
                    "owner": draft.owner,
                    "repo": draft.repo,
                    "number": draft.number,
                    "issue_ref": draft.issue_ref,
                    "issue_url": draft.issue_url,
                    "title": draft.title,
                    "summary": draft.summary,
                    "problem_statement": draft.problem_statement,
                    "labels": list(draft.labels),
                    "intake_status": draft.intake_status,
                    "intake_reason_codes": list(draft.intake_reason_codes),
                    "provenance": {
                        "source_artifacts": list(draft.provenance.source_artifacts),
                        "requested_issue_ref": draft.provenance.requested_issue_ref,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # Write issue-review.json
    if include_issue_review:
        review = _make_issue_review_approved(record.run_id, issue_ref)
        if not issue_review_approved:
            review = IssueReview(
                run_id=review.run_id,
                issue_ref=review.issue_ref,
                review_status="changes_requested",
                summary=review.summary,
                feedback=review.feedback,
                provenance=review.provenance,
            )
        store.write_issue_review(run_dir, review)

    # Write approved-plan.json
    if include_approved_plan:
        store.write_approved_plan(run_dir, _approved_plan(issue_ref))

    # Write plan-review.json
    if include_plan_review:
        review = _make_plan_review_approved(record.run_id, issue_ref)
        if not plan_review_approved:
            review = PlanReview(
                run_id=review.run_id,
                issue_ref=review.issue_ref,
                review_status="changes_requested",
                summary=review.summary,
                feedback=review.feedback,
                provenance=review.provenance,
            )
        store.write_plan_review(run_dir, review)

    # Write governance-verdict.json (approved)
    store.write_governance_verdict(
        run_dir,
        GovernanceVerdict(status="approved", summary="Approved", reason_codes=()),
    )

    # Write execution-result.json
    store.write_execution_result(
        run_dir,
        ExecutionResult(
            status="completed",
            executor_name="test",
            summary="Test execution",
            detail_codes=(),
        ),
    )

    # Write evaluation-result.json
    store.write_evaluation_result(
        run_dir,
        EvaluationResult(status="success", summary="Evaluation passed", detail_codes=()),
    )

    # Write repair-result.json (completed with workspace_path)
    repair_result = RepairResult(
        status="completed",
        summary="Repair completed",
        detail_codes=(),
        workspace_path=str(run_dir / "repair-workspace" / "repo"),
    )
    store.write_repair_result(run_dir, repair_result)

    # Write qa-baseline-result.json
    store.write_qa_result(
        run_dir,
        QaResult(
            status="passed",
            summary="QA passed",
            detail_codes=(),
            phase="baseline",
            quality="green",
        ),
    )

    # Write qa-result.json
    store.write_qa_result(
        run_dir,
        QaResult(
            status="passed",
            summary="QA passed",
            detail_codes=(),
            phase="final",
            quality="green",
        ),
    )

    # Write decision-log artifact
    decision_log = DecisionLogArtifact(
        attempt=attempt,
        entries=(
            DesignDecision(
                sequence=1,
                summary="Initial decision",
                rationale="This is the first decision",
                plan_steps=("Step 1",),
                named_references=(),
                affected_targets=(),
            ),
        ),
    )
    store.write_decision_log(run_dir, decision_log)

    # Create repair-workspace/repo directory
    workspace = run_dir / "repair-workspace" / "repo"
    workspace.mkdir(parents=True, exist_ok=True)

    return store, updated


RetryResumeStage = str  # For type alias purposes in tests


def _make_params_for_resume(
    tmp_path: Path,
    retry_from: str,
    *,
    resume_from: Literal["publish", "review impl"] | None = None,
) -> RepairIssueParams:
    """Create RepairIssueParams for a resume test."""
    return RepairIssueParams(
        issue_ref="owner/repo#1",
        runs_dir=tmp_path / "runs",
        repo_path=tmp_path / "repo",
        publish=False,
        repair_agent="none",
        repair_model=None,
        review_model=None,
        retry_from=retry_from,
        resume_from=resume_from,
        approved_plan=None,
    )


# ---------------------------------------------------------------------------
# Tests for publish resume preflight validation
# ---------------------------------------------------------------------------


def test_retry_from_publish_without_issue_draft_fails(tmp_path: Path) -> None:
    """Test that --from publish fails when issue-draft.json is missing."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    _, previous = _create_publish_resume_source_run(
        store,
        attempt=1,
        include_issue_draft=False,  # Missing issue-draft.json
    )

    coordinator = RunCoordinator()

    with pytest.raises(ValueError, match="Retry resume requires issue-draft.json"):
        coordinator.repair_issue(
            params=_make_params_for_resume(tmp_path, previous.run_id, resume_from="publish"),
            intake=_make_intake(),
            dependencies=MagicMock(),
        )


def test_retry_from_publish_without_issue_review_fails(tmp_path: Path) -> None:
    """Test that --from publish fails when issue-review.json is missing."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    _, previous = _create_publish_resume_source_run(
        store,
        attempt=1,
        include_issue_review=False,  # Missing issue-review.json
    )

    coordinator = RunCoordinator()

    with pytest.raises(ValueError, match="Retry resume to publish requires issue-review.json"):
        coordinator.repair_issue(
            params=_make_params_for_resume(tmp_path, previous.run_id, resume_from="publish"),
            intake=_make_intake(),
            dependencies=MagicMock(),
        )


def test_retry_from_publish_with_non_approved_issue_review_fails(tmp_path: Path) -> None:
    """Test that --from publish fails when issue-review.json is not approved."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    _, previous = _create_publish_resume_source_run(
        store,
        attempt=1,
        issue_review_approved=False,  # Not approved
    )

    coordinator = RunCoordinator()

    with pytest.raises(
        ValueError, match="Retry resume to publish requires approved issue-review.json"
    ):
        coordinator.repair_issue(
            params=_make_params_for_resume(tmp_path, previous.run_id, resume_from="publish"),
            intake=_make_intake(),
            dependencies=MagicMock(),
        )


def test_retry_from_publish_without_plan_review_fails(tmp_path: Path) -> None:
    """Test that --from publish fails when plan-review.json is missing."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    _, previous = _create_publish_resume_source_run(
        store,
        attempt=1,
        include_plan_review=False,  # Missing plan-review.json
    )

    coordinator = RunCoordinator()

    with pytest.raises(ValueError, match="Retry resume to publish requires plan-review.json"):
        coordinator.repair_issue(
            params=_make_params_for_resume(tmp_path, previous.run_id, resume_from="publish"),
            intake=_make_intake(),
            dependencies=MagicMock(),
        )


def test_retry_from_publish_with_non_approved_plan_review_fails(tmp_path: Path) -> None:
    """Test that --from publish fails when plan-review.json is not approved."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)
    _, previous = _create_publish_resume_source_run(
        store,
        attempt=1,
        plan_review_approved=False,  # Not approved
    )

    coordinator = RunCoordinator()

    with pytest.raises(
        ValueError, match="Retry resume to publish requires approved plan-review.json"
    ):
        coordinator.repair_issue(
            params=_make_params_for_resume(tmp_path, previous.run_id, resume_from="publish"),
            intake=_make_intake(),
            dependencies=MagicMock(),
        )


# ---------------------------------------------------------------------------
# Tests for review impl resume preflight validation
# ---------------------------------------------------------------------------


def test_retry_from_review_impl_with_non_approved_plan_review_fails(tmp_path: Path) -> None:
    """Test that --from review impl fails when plan-review.json is not approved."""
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)

    # Create a basic source run with an unapproved plan-review
    _, previous = _create_publish_resume_source_run(
        store,
        attempt=1,
        plan_review_approved=False,  # Not approved
    )

    coordinator = RunCoordinator()

    with pytest.raises(
        ValueError, match="Implement ingress requires plan-review.json.review_status to be 'approved'"
    ):
        coordinator.repair_issue(
            params=_make_params_for_resume(tmp_path, previous.run_id, resume_from="review impl"),
            intake=_make_intake(),
            dependencies=MagicMock(),
        )

