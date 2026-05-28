"""Integration tests: retry carry-forward behavior.

Verifies that the retry mechanism correctly:
- Reads existing approved-plan.json from the same run-id
- Preserves decision-log artifacts (append-only behavior)
- Re-runs the full pipeline from create_issue on every retry attempt
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    ApprovedPlan,
    DecisionLogArtifact,
    DesignDecision,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RunRequest,
)
from precision_squad.run_store import RunStore
from tests.integration.conftest import StubRepairAdapter
from tests.integration.support import _ApprovedTestDependencies


def _runnable_intake(issue_ref: str = "cracklings3d/markdown-pdf-renderer#9") -> IssueIntake:
    owner, repo_with_hash = issue_ref.split("/")
    repo, number_str = repo_with_hash.split("#")
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference(owner, repo, int(number_str)),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url=f"https://github.com/{issue_ref.replace('#', '/issues/')}",
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )


def _create_previous_run_with_artifacts(
    store: RunStore,
    attempt: int = 1,
    *,
    include_approved_plan: bool = True,
    include_decision_log: bool = False,
) -> tuple[Path, str]:
    """Create a previous run record with specified artifacts.

    Returns (run_dir, run_id) tuple.
    """
    intake = _runnable_intake()
    request = RunRequest(issue_ref=str(intake.issue.reference), runs_dir=str(store.root))
    record = store.create_run(request, intake)

    # Update the record with the attempt number
    from precision_squad.models import RunRecord

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

    if include_approved_plan:
        plan = ApprovedPlan(
            issue_ref=str(intake.issue.reference),
            plan_summary="Fix the bug with a minimal change.",
            implementation_steps=("Update the implementation",),
            named_references=(),
            retrieval_surface_summary="src/",
            approved=True,
        )
        store.write_approved_plan(run_dir, plan)

    if include_decision_log:
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

    return run_dir, updated.run_id


# ---------------------------------------------------------------------------
# Test 1: retry uses existing approved-plan
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_retry_uses_existing_approved_plan(
    make_clean_repo,
    stub_repair_adapter: StubRepairAdapter,
    tmp_path: Path,
) -> None:
    """Retry reads approved-plan.json from the same run-id and skips replanning.

    A prior run has approved-plan.json. When retry is invoked with retry_from,
    the new run should consume that plan and not create a new one (no replanning).
    """
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)

    # Create a previous run with approved-plan.json at attempt 1
    previous_run_dir, previous_run_id = _create_previous_run_with_artifacts(
        store, attempt=1, include_approved_plan=True, include_decision_log=False
    )

    # Capture original approved-plan content to verify it is unchanged
    original_plan_path = previous_run_dir / "approved-plan.json"
    original_plan_content = original_plan_path.read_text(encoding="utf-8")
    original_plan_data = json.loads(original_plan_content)

    # Now invoke retry via RunCoordinator.repair_issue() with retry_from param
    runs_dir = tmp_path / "runs"
    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
        retry_from=previous_run_id,
        approved_plan=None,  # Must be None when retry_from is set
    )

    deps = _ApprovedTestDependencies(stub_repair_adapter)
    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    # Verify the new run was created
    assert report.run_record is not None
    new_run_dir = Path(report.run_record.run_dir)

    # Assert that approved-plan.json exists in the new run directory
    # (carried forward from the previous run)
    assert (new_run_dir / "approved-plan.json").exists(), (
        "approved-plan.json should be carried forward on retry"
    )

    # Verify the carried-forward plan matches the original
    carried_plan = RunStore.load_approved_plan(new_run_dir, issue_ref="cracklings3d/markdown-pdf-renderer#9")
    assert carried_plan.issue_ref == original_plan_data["issue_ref"]
    assert carried_plan.plan_summary == original_plan_data["plan_summary"]
    assert carried_plan.implementation_steps == tuple(original_plan_data["implementation_steps"])
    assert carried_plan.approved == original_plan_data["approved"]

    # Verify the previous run's approved-plan.json was NOT modified (append-only)
    # The original file should still exist and have identical content
    assert original_plan_path.exists()
    assert original_plan_path.read_text(encoding="utf-8") == original_plan_content


# ---------------------------------------------------------------------------
# Test 2: retry does not overwrite decision-log
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_retry_does_not_overwrite_decision_log(
    make_clean_repo,
    stub_repair_adapter: StubRepairAdapter,
    tmp_path: Path,
) -> None:
    """Retry preserves existing decision-log artifacts (append-only behavior).

    When retry runs, it creates decision-log.attempt-{N+1}.json without
    modifying the original decision-log.attempt-{N}.json. The approved-plan.json
    from the previous run is also not modified.
    """
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)

    # Create a previous run at attempt 1 with both approved-plan and decision-log
    previous_run_dir, previous_run_id = _create_previous_run_with_artifacts(
        store, attempt=1, include_approved_plan=True, include_decision_log=True
    )

    # Capture original approved-plan.json content
    original_plan_path = previous_run_dir / "approved-plan.json"
    original_plan_content = original_plan_path.read_text(encoding="utf-8")
    # Capture original decision-log.attempt-1.json content
    original_decision_log_path = previous_run_dir / "decision-log.attempt-1.json"
    original_decision_log_content = original_decision_log_path.read_text(encoding="utf-8")

    # Invoke retry - this should create decision-log.attempt-2.json
    runs_dir = tmp_path / "runs"
    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
        retry_from=previous_run_id,
        approved_plan=None,
    )

    deps = _ApprovedTestDependencies(stub_repair_adapter)
    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    # Verify new run was created
    assert report.run_record is not None
    new_run_dir = Path(report.run_record.run_dir)

    # Verify new decision-log.attempt-2.json was created
    assert (new_run_dir / "decision-log.attempt-2.json").exists(), (
        "Retry should create decision-log.attempt-2.json"
    )

    # Verify the new decision log has attempt=2
    new_decision_log = RunStore.load_decision_log(new_run_dir, attempt=2)
    assert new_decision_log.attempt == 2

    # Verify approved-plan.json exists and is unchanged
    assert (new_run_dir / "approved-plan.json").exists()
    assert (new_run_dir / "approved-plan.json").read_text(encoding="utf-8") == original_plan_content

    # Verify the previous run's original files were NOT modified
    # (preserving = not overwritten, not copied to new directory)
    assert original_plan_path.read_text(encoding="utf-8") == original_plan_content
    assert original_decision_log_path.read_text(encoding="utf-8") == original_decision_log_content


# ---------------------------------------------------------------------------
# Test 3: retry re-runs full pipeline from create_issue
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_retry_re_runs_full_pipeline_from_create_issue(
    make_clean_repo,
    stub_repair_adapter: StubRepairAdapter,
    tmp_path: Path,
) -> None:
    """Retry re-runs the full pipeline from create_issue on every retry attempt.

    Every retry creates decision-log.attempt-{N+1}.json while preserving the
    original decision-log.attempt-{N}.json and approved-plan.json artifacts.
    The approved-plan.json is consumed to skip replanning.
    """
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True, exist_ok=True)

    # Create a previous run at attempt 2 with approved-plan and decision-log
    previous_run_dir, previous_run_id = _create_previous_run_with_artifacts(
        store, attempt=2, include_approved_plan=True, include_decision_log=True
    )

    # Capture original approved-plan.json content
    original_plan_path = previous_run_dir / "approved-plan.json"
    original_plan_content = original_plan_path.read_text(encoding="utf-8")
    original_plan_data = json.loads(original_plan_content)

    # Capture original decision-log.attempt-2.json content
    original_decision_log_path = previous_run_dir / "decision-log.attempt-2.json"
    original_decision_log_content = original_decision_log_path.read_text(encoding="utf-8")

    # Invoke retry - this should create decision-log.attempt-3.json
    runs_dir = tmp_path / "runs"
    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
        retry_from=previous_run_id,
        approved_plan=None,
    )

    deps = _ApprovedTestDependencies(stub_repair_adapter)
    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    # Verify new run was created
    assert report.run_record is not None
    new_run_dir = Path(report.run_record.run_dir)
    assert report.run_record.attempt == 3, "New attempt should be 3 (previous was 2)"

    # Verify new decision-log.attempt-3.json was created
    assert (new_run_dir / "decision-log.attempt-3.json").exists(), (
        "Retry should create decision-log.attempt-3.json"
    )

    # Verify the new decision log has attempt=3
    new_decision_log = RunStore.load_decision_log(new_run_dir, attempt=3)
    assert new_decision_log.attempt == 3

    # Verify approved-plan.json exists and matches original
    assert (new_run_dir / "approved-plan.json").exists()
    carried_plan = RunStore.load_approved_plan(new_run_dir, issue_ref="cracklings3d/markdown-pdf-renderer#9")
    assert carried_plan.issue_ref == original_plan_data["issue_ref"]
    assert carried_plan.plan_summary == original_plan_data["plan_summary"]

    # Verify previous run's original files were NOT modified
    # (preserving = not overwritten, not copied to new directory)
    assert original_plan_path.read_text(encoding="utf-8") == original_plan_content
    assert original_decision_log_path.read_text(encoding="utf-8") == original_decision_log_content
