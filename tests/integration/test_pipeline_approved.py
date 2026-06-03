"""Integration tests: approved pipeline path through RunCoordinator.

Exercises the full happy path with:
- Real DocsFirstExecutor against clean-python fixture
- Stub repair adapter that makes a trivial file change
- Real QA verifier (pwsh + pytest)
- Governance approval
- Dry-run publish plan
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
)
from tests.integration.support import _ApprovedTestDependencies, approved_plan_for


def _runnable_intake() -> IssueIntake:
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
# Happy path: clean docs -> repair (stub) -> QA passes -> governance approved
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_approved_happy_path(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """Full pipeline with clean docs, stub repair, and passing QA: governance approved."""
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

    assert report.execution_result is not None
    assert report.execution_result.status == "completed"
    assert report.execution_result.executor_name == "docs+repair"
    assert report.repair_result is not None
    assert report.repair_result.status == "completed"
    assert report.qa_result is not None
    assert report.qa_result.status == "passed"
    assert report.qa_result.quality == "green"
    assert report.baseline_qa_result is not None
    assert report.governance_verdict is not None
    assert report.publish_plan is not None
    assert report.publish_result is not None
    assert report.governance_verdict.verdict == "approved"
    assert report.publish_plan.status == "draft_pr"
    assert report.publish_result.status == "dry_run"
    assert report.exit_code == 0


@pytest.mark.integration
def test_approved_persists_all_artifacts(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """Approved run writes every expected JSON artifact to the run directory."""
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

    run_dir = Path(report.run_record.run_dir)
    expected = [
        "run-request.json",
        "issue-intake.json",
        "issue-draft.json",
        "run-record.json",
        "execution-result.json",
        "repair-result.json",
        "qa-baseline-result.json",
        "qa-result.json",
        "evaluation-result.json",
        "governance-verdict.json",
        "publish-plan.json",
        "publish-result.json",
    ]
    for artifact in expected:
        assert (run_dir / artifact).exists(), f"{artifact} should be written"

    repair_result = json.loads((run_dir / "repair-result.json").read_text(encoding="utf-8"))
    assert repair_result["status"] == "completed"
    assert repair_result["workspace_path"] is not None

    qa_result = json.loads((run_dir / "qa-result.json").read_text(encoding="utf-8"))
    assert qa_result["status"] == "passed"
    assert qa_result["phase"] == "final"


@pytest.mark.integration
def test_approved_qa_result_has_correct_phase(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """Baseline QA and final QA are distinct phases with correct phase markers."""
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

    assert report.baseline_qa_result is not None
    assert report.baseline_qa_result.phase == "baseline"
    assert report.qa_result is not None
    assert report.qa_result.phase == "final"
    assert report.qa_result.status == "passed"


@pytest.mark.integration
def test_approved_publish_plan_has_required_fields(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """Approved publish plan is a draft_pr with title, body, and branch_name."""
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

    plan = report.publish_plan
    assert plan is not None
    assert plan.status == "draft_pr"
    assert plan.title
    assert plan.body
    assert "run-" in plan.body


@pytest.mark.integration
def test_approved_exit_code_is_zero(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """An approved run exits with code 0."""
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

    assert report.exit_code == 0


