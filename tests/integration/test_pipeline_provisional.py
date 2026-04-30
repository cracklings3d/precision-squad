"""Integration tests: provisional (baseline-tolerant) pipeline path.

Exercises the baseline-tolerance logic: when the baseline QA fails but the
repair improves the failure set without introducing new failures, governance
marks the run as provisional.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    GitHubIssue,
    IssueAssessment,
    IssueReference,
    IssueIntake,
)
from tests.integration.test_pipeline_approved import _ApprovedTestDependencies


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


class _RepairAdapterThatFixesFailingTest:
    """Stub adapter that removes the intentionally failing test.

    The make_repo_with_failing_tests fixture has a test_fail() that calls
    fail() which raises RuntimeError. This adapter removes test_fail() from
    the test file, so the remaining test_greet() passes.
    """

    def __init__(self) -> None:
        self.binary: str | None = None
        self.agent: str | None = None
        self.model: str | None = None
        self.qa_feedback: str | None = None

    def repair(
        self,
        *,
        intake: IssueIntake,
        run_record,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
    ):
        import subprocess

        test_file = repo_workspace / "tests" / "test_core.py"
        if test_file.exists():
            original = test_file.read_text(encoding="utf-8")
            fixed = original.replace(
                "\ndef test_fail():\n    fail()  # This test fails intentionally\n",
                "",
            )
            test_file.write_text(fixed, encoding="utf-8")

        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "repair: remove intentionally failing test"],
            cwd=repo_workspace,
            check=True,
            capture_output=True,
        )

        patch_proc = subprocess.run(
            ["git", "diff", "--binary", "HEAD~1", "HEAD"],
            cwd=repo_workspace,
            capture_output=True,
            text=True,
        )
        patch_path = run_dir / "repair.patch"
        patch_path.write_text(patch_proc.stdout or "", encoding="utf-8")

        from precision_squad.models import RepairResult

        return RepairResult(
            status="completed",
            summary="Stub repair removed intentionally failing test.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repo_workspace.parent),
            patch_path=str(patch_path),
        )


@pytest.mark.integration
def test_broken_baseline_improved_to_provisional(
    make_repo_with_failing_tests,
    tmp_path: Path,
) -> None:
    """Baseline fails (test_fail), repair removes it, final QA passes -> provisional."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_repo_with_failing_tests,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
    )

    deps = _ProvisionalTestDependencies()

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    assert report.execution_result is not None
    assert report.baseline_qa_result is not None
    assert report.baseline_qa_result.phase == "baseline"
    assert report.baseline_qa_result.status in {"failed", "failed_infra"}, (
        f"baseline should fail: {report.baseline_qa_result.status}"
    )

    assert report.qa_result is not None
    assert report.qa_result.phase == "final"
    assert report.qa_result.status in {"passed", "provisional"}, (
        f"final QA should be passed or provisional: {report.qa_result.status}"
    )

    assert report.governance_verdict.status == "provisional", (
        f"Expected provisional, got {report.governance_verdict.status}: "
        f"{report.governance_verdict.summary}"
    )
    assert report.publish_plan.status == "draft_pr"
    assert report.exit_code == 5


@pytest.mark.integration
def test_provisional_publish_plan_contains_provisional_context(
    make_repo_with_failing_tests,
    tmp_path: Path,
) -> None:
    """Provisional publish plan body should mention the provisional status."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_repo_with_failing_tests,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
    )

    deps = _ProvisionalTestDependencies()

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    plan = report.publish_plan
    assert plan.status == "draft_pr"
    assert "provisional" in plan.body.lower() or "qa_baseline_improved" in plan.body.lower()


class _ProvisionalTestDependencies(_ApprovedTestDependencies):
    """Dependencies for the provisional path that use the failing-test repair adapter."""

    def __init__(self) -> None:
        self._adapter = _RepairAdapterThatFixesFailingTest()

    def create_repair_adapter(
        self, *, repair_agent: str, repair_model: str | None
    ):
        if repair_agent == "none":
            return None
        return self._adapter
