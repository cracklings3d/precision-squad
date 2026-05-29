"""Integration tests: plan gate behavior and happy-path chain through RunCoordinator.

Verifies that chained execution:
1. Auto-approves a fresh compatibility run with no approved_plan override
2. Stops at governance gate (blocked verdict → no publish)
3. Completes full happy path with all stages invoked
4. Only invokes publish when governance verdict is approved
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import pytest

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    ExecutionResult,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    PublishResult,
)
from tests.integration.support import _ApprovedTestDependencies, approved_plan_for


def _runnable_intake(
    issue_ref: str = "cracklings3d/markdown-pdf-renderer#9",
) -> IssueIntake:
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


# ---------------------------------------------------------------------------
# Test 1: Fresh run blocks without explicit approved plan
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_chain_blocks_fresh_run_without_explicit_plan(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """Fresh attempt-1 without explicit approved_plan must block at review plan.

    The compatibility auto-approval path has been removed. Fresh runs without
    a current-run approved plan artifact must stop at the review plan gate.
    """
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
        # NOTE: approved_plan intentionally omitted - should block at review plan
    )

    deps = _ApprovedTestDependencies(stub_repair_adapter)

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    run_dir = Path(report.run_record.run_dir)

    # Fresh run without approved plan must block
    assert report.exit_code == 3, "fresh run should block at review_plan"
    assert report.plan_review is not None, "review_plan should run"
    assert report.plan_review.review_status == "blocked", "review_plan should be blocked"
    assert not (run_dir / "approved-plan.json").exists(), \
        "no approved-plan.json should exist for fresh run without explicit plan"
    assert report.execution_result is None, "implement should not run when blocked"


@pytest.mark.integration
@pytest.mark.parametrize("review_stages", ["plan", "all"])
def test_chain_preserves_explicit_plan_gating_without_approved_plan(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
    review_stages: str,
) -> None:
    """Explicit review-stage gating must still stop runs lacking an approved plan."""
    review_stages_value = cast(Literal["plan", "all"], review_stages)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
        review_stages=review_stages_value,
    )

    deps = _ApprovedTestDependencies(stub_repair_adapter)

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    run_dir = Path(report.run_record.run_dir)
    assert report.exit_code == 3
    assert not (run_dir / "approved-plan.json").exists()
    assert report.execution_result is None
    assert report.plan_review is not None
    assert report.plan_review.review_status == "blocked"
    assert report.publish_plan is None
    assert report.publish_result is None


# ---------------------------------------------------------------------------
# Test 2: Chain stops at governance gate (blocked verdict → no publish)
# ---------------------------------------------------------------------------

class _GovernanceBlockedTestDependencies(_ApprovedTestDependencies):
    """Dependencies that simulate governance blocking after successful implementation."""

    def merge_execution_result(self, synthesis_result, repair_result, qa_result=None):
        # Return a blocked execution result to trigger governance blocked
        return ExecutionResult(
            status="blocked",
            executor_name="docs+repair",
            summary="Blocked by test dependency",
            detail_codes=("blocked_by_test",),
        )


@pytest.mark.integration
def test_chain_stops_at_governance_not_approved(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """When governance verdict is blocked, publish is not invoked.

    _GovernanceBlockedTestDependencies.merge_execution_result returns a blocked
    ExecutionResult, which triggers a blocked governance verdict. The chain
    stops after implement_run and publish is never invoked.
    """
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
        approved_plan=approved_plan_for(),
    )

    deps = _GovernanceBlockedTestDependencies(stub_repair_adapter)

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    assert report.exit_code != 0, "chain should stop at governance gate"
    assert report.governance_verdict is not None, "governance should run"
    assert report.governance_verdict.status == "blocked", "governance should be blocked"
    assert report.publish_plan is None, "publish_plan should not run"
    assert report.publish_result is None, "publish_result should not run"


# ---------------------------------------------------------------------------
# Test 3: Happy path chain completes with all stages invoked
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_happy_path_chain_complete(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """Full happy path: all stages return approved and chain completes.

    With approved_plan provided, review_plan proceeds with exit_code 0.
    Since execute_publish_plan returns status="dry_run", post_publish_review_result
    will be None (review_impl skipped in dry_run mode).
    """
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
        approved_plan=approved_plan_for(),
    )

    deps = _ApprovedTestDependencies(stub_repair_adapter)

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    assert report.issue_review is not None
    assert report.issue_review.review_status == "approved"
    assert report.plan_review is not None
    assert report.plan_review.review_status == "approved"
    assert report.execution_result is not None
    assert report.repair_result is not None
    assert report.qa_result is not None
    assert report.baseline_qa_result is not None
    assert report.governance_verdict is not None
    assert report.governance_verdict.status == "approved"
    assert report.publish_plan is not None
    assert report.publish_plan.status == "draft_pr"
    assert report.publish_result is not None
    assert report.publish_result.status == "dry_run"
    # In dry_run mode, post_publish_review_result is None because
    # review_impl only runs when publish_result.status == "published"
    assert report.post_publish_review_result is None
    assert report.exit_code == 0


# ---------------------------------------------------------------------------
# Test 4: publish is invoked only when governance verdict is approved
# ---------------------------------------------------------------------------

class _PublishCalledSpy(_ApprovedTestDependencies):
    """Spy wrapper that records whether execute_publish_plan was invoked."""

    def __init__(self, adapter):
        super().__init__(adapter)
        self._publish_called = False

    @property
    def publish_called(self) -> bool:
        return self._publish_called

    def execute_publish_plan(
        self, intake, plan, *, publish, run_dir=None
    ) -> PublishResult:
        self._publish_called = True
        return super().execute_publish_plan(intake, plan, publish=publish, run_dir=run_dir)


@pytest.mark.integration
def test_publish_only_after_approved_verdict(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """publish_plan.execute is only called when governance verdict is approved.

    Uses a spy subclass of _ApprovedTestDependencies that records whether
    execute_publish_plan was invoked. Runs two scenarios:
    1. With governance blocked → execute_publish_plan should NOT be called
    2. With governance approved → execute_publish_plan SHOULD be called
    """
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Scenario 1: Governance blocked - publish should NOT be called
    params_blocked = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir / "blocked",
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
        approved_plan=approved_plan_for(),
    )

    blocked_deps = _GovernanceBlockedTestDependencies(stub_repair_adapter)

    report_blocked = RunCoordinator().repair_issue(
        params=params_blocked,
        intake=_runnable_intake(),
        dependencies=blocked_deps,
    )

    assert report_blocked.governance_verdict is not None
    assert report_blocked.governance_verdict.status == "blocked"
    # Cannot directly observe that execute_publish_plan was not called using
    # _GovernanceBlockedTestDependencies, but we can verify the chain stopped
    assert report_blocked.publish_plan is None
    assert report_blocked.publish_result is None

    # Scenario 2: Governance approved - publish SHOULD be called
    spy_deps = _PublishCalledSpy(stub_repair_adapter)

    params_approved = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir / "approved",
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
        approved_plan=approved_plan_for(),
    )

    report_approved = RunCoordinator().repair_issue(
        params=params_approved,
        intake=_runnable_intake(),
        dependencies=spy_deps,
    )

    assert report_approved.governance_verdict is not None
    assert report_approved.governance_verdict.status == "approved"
    assert spy_deps.publish_called is True, "execute_publish_plan should be called when approved"
    assert report_approved.publish_plan is not None
    assert report_approved.publish_result is not None
