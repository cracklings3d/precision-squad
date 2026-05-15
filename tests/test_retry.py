"""Tests for the retry mechanism in RunCoordinator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    ApprovedPlan,
    ExecutionResult,
    GitHubIssue,
    GovernanceVerdict,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    PublishPlan,
    PublishResult,
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
    )


def _create_previous_run(store: RunStore, attempt: int = 1) -> RunRecord:
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
    carried_forward = RunStore.load_approved_plan(new_run_dir)
    assert carried_forward is not None
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
    report = coordinator.repair_issue(
        params=_make_params(tmp_path, retry_from=previous.run_id),
        intake=_make_intake(),
        dependencies=MagicMock(),
    )

    assert report.exit_code == 3
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
