"""Integration tests: blocked pipeline paths through RunCoordinator.

Exercises the full pipeline with intake or documentation conditions that
produce a blocked governance verdict, verifying that the right short-circuit
occurs and the correct publish plan is produced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    ExecutionResult,
    IssueIntake,
    PublishResult,
)

# ---------------------------------------------------------------------------
# Blocked intake: plan issue skips the executor entirely
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_plan_issue_blocks_before_executor(
    plan_issue_intake: IssueIntake,
    tmp_path: Path,
) -> None:
    """A plan-labeled issue produces a blocked verdict without running the executor."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#1",
        runs_dir=runs_dir,
        repo_path=repo_path,
        publish=False,
        repair_agent="none",
        repair_model=None,
        review_model=None,
    )

    report = RunCoordinator().repair_issue(
        params=params,
        intake=plan_issue_intake,
        dependencies=_BlockedTestDependencies(),
    )

    assert report.execution_result is None, "executor should not run for blocked intake"
    assert report.governance_verdict is not None
    assert report.governance_verdict.status == "blocked"
    assert report.publish_plan is not None
    assert report.publish_plan.status == "issue_comment"
    assert report.publish_result is not None
    assert report.publish_result.status == "dry_run"
    assert report.exit_code == 3

    run_dir = Path(report.run_record.run_dir)
    assert (run_dir / "run-request.json").exists()
    assert (run_dir / "issue-intake.json").exists()
    assert (run_dir / "run-record.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert (run_dir / "publish-plan.json").exists()
    assert (run_dir / "publish-result.json").exists()


# ---------------------------------------------------------------------------
# Missing docs: executor runs, finds missing docs, governance blocks
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_missing_docs_blocks_pipeline(
    make_empty_repo,
    tmp_path: Path,
) -> None:
    """A repo with no README triggers missing_docs and a follow_up_issue publish plan."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_empty_repo,
        publish=False,
        repair_agent="none",
        repair_model=None,
        review_model=None,
    )

    from precision_squad.models import GitHubIssue, IssueAssessment, IssueReference

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

    report = RunCoordinator().repair_issue(
        params=params,
        intake=intake,
        dependencies=_BlockedTestDependencies(),
    )

    assert report.execution_result is not None
    assert report.execution_result.status == "missing_docs"
    assert report.governance_verdict.status == "blocked"
    assert report.publish_plan.status == "follow_up_issue"
    assert report.publish_result.status == "dry_run"
    assert report.exit_code == 4


@pytest.mark.integration
def test_missing_docs_persists_execution_artifacts(
    make_empty_repo,
    tmp_path: Path,
) -> None:
    """Missing-docs run still persists all expected artifacts."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_empty_repo,
        publish=False,
        repair_agent="none",
        repair_model=None,
        review_model=None,
    )

    from precision_squad.models import GitHubIssue, IssueAssessment, IssueReference

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

    report = RunCoordinator().repair_issue(
        params=params,
        intake=intake,
        dependencies=_BlockedTestDependencies(),
    )

    run_dir = Path(report.run_record.run_dir)
    assert (run_dir / "execution-result.json").exists()
    assert (run_dir / "evaluation-result.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert (run_dir / "publish-plan.json").exists()
    assert (run_dir / "publish-result.json").exists()
    assert not (run_dir / "repair-result.json").exists(), "repair should not run when docs missing"


# ---------------------------------------------------------------------------
# Ambiguous docs: executor runs, finds ambiguous docs, governance blocks
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_ambiguous_docs_blocks_pipeline(
    make_ambiguous_repo,
    tmp_path: Path,
) -> None:
    """Conflicting setup instructions trigger ambiguous_docs and follow_up_issue plan."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_ambiguous_repo,
        publish=False,
        repair_agent="none",
        repair_model=None,
        review_model=None,
    )

    from precision_squad.models import GitHubIssue, IssueAssessment, IssueReference

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

    report = RunCoordinator().repair_issue(
        params=params,
        intake=intake,
        dependencies=_BlockedTestDependencies(),
    )

    assert report.execution_result is not None
    assert report.execution_result.status == "ambiguous_docs"
    assert report.governance_verdict.status == "blocked"
    assert report.publish_plan.status == "follow_up_issue"
    assert report.exit_code == 4


# ---------------------------------------------------------------------------
# Blocked execution result from a custom executor stub
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_blocked_execution_result_blocks_pipeline(
    make_clean_repo,
    tmp_path: Path,
) -> None:
    """Even with a clean repo, a blocked execution result produces a blocked verdict."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="none",
        repair_model=None,
        review_model=None,
    )

    from precision_squad.models import GitHubIssue, IssueAssessment, IssueReference

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

    report = RunCoordinator().repair_issue(
        params=params,
        intake=intake,
        dependencies=_BlockedTestDependencies(),
    )

    assert report.execution_result is not None
    assert report.execution_result.status in {
        "completed",
        "blocked",
        "missing_docs",
    }


# ---------------------------------------------------------------------------
# QA failed: repair completes but QA fails -> blocked verdict, quality=degraded
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_qa_failed_blocks_pipeline(
    make_clean_repo,
    tmp_path: Path,
) -> None:
    """When repair completes but QA fails, governance blocks with quality=degraded."""
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
    )

    from precision_squad.models import GitHubIssue, IssueAssessment, IssueReference

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

    deps = _QaFailedTestDependencies()

    report = RunCoordinator().repair_issue(
        params=params,
        intake=intake,
        dependencies=deps,
    )

    assert report.repair_result is not None
    assert report.repair_result.status == "completed"
    assert report.qa_result is not None
    assert report.qa_result.status == "failed"
    assert report.qa_result.quality == "degraded"
    assert report.governance_verdict.status == "blocked"
    assert report.exit_code == 4


# ---------------------------------------------------------------------------
# Test dependencies (blocks executor + all external calls)
# ---------------------------------------------------------------------------

class _BlockedTestDependencies:
    """Replacement dependencies that block all repair and publishing."""

    def create_repair_adapter(
        self, *, repair_agent: str, repair_model: str | None
    ):
        return None

    def run_repair_qa_loop(self, **kwargs):
        raise AssertionError("repair loop should not run for blocked intake")

    def run_docs_remediation_repair(self, **kwargs):
        raise AssertionError("docs remediation should not run for blocked intake")

    def evaluate_docs_remediation_validation(self, **kwargs):
        raise AssertionError("validation should not run for blocked intake")

    def merge_docs_remediation_execution_result(self, *args, **kwargs):

        return ExecutionResult(
            status="blocked",
            executor_name="docs",
            summary="blocked by test",
            detail_codes=("blocked_by_test",),
        )

    def merge_execution_result(self, synthesis_result, repair_result, qa_result=None):
        return synthesis_result

    def synthesis_artifacts_ready(self, execution_result):
        return False

    def execute_publish_plan(self, intake, plan, *, publish, run_dir=None):
        return PublishResult(
            status="dry_run",
            target=plan.status,
            summary="dry_run (test)",
            url=None,
        )

    def run_post_publish_review_if_needed(self, **kwargs):
        return None


class _QaFailedTestDependencies:
    """Dependencies that simulate a QA failure after successful repair."""

    def __init__(self) -> None:
        self._adapter = _StubRepairAdapter()

    def create_repair_adapter(
        self, *, repair_agent: str, repair_model: str | None
    ):
        if repair_agent == "none":
            return None
        return self._adapter

    def run_repair_qa_loop(self, *, repo_path, adapter, intake, run_record, run_dir, contract_artifact_dir):
        from precision_squad.models import QaResult, RepairResult

        repair_result = RepairResult(
            status="completed",
            summary="Stub repair completed.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repo_path.parent),
        )
        baseline_result = QaResult(
            status="passed",
            summary="Baseline QA passed.",
            detail_codes=(),
            phase="baseline",
            quality="green",
        )
        qa_result = QaResult(
            status="failed",
            summary="QA failed: test_new_feature FAILED",
            detail_codes=("qa_failed",),
            phase="final",
            quality="degraded",
        )
        return repair_result, baseline_result, qa_result

    def run_docs_remediation_repair(self, **kwargs):
        raise AssertionError("docs remediation should not run")

    def evaluate_docs_remediation_validation(self, **kwargs):
        raise AssertionError("validation should not run")

    def merge_docs_remediation_execution_result(self, *args, **kwargs):
        raise AssertionError("docs remediation merge should not run")

    def merge_execution_result(self, synthesis_result, repair_result, qa_result=None):
        from precision_squad.models import ExecutionResult

        if qa_result and qa_result.status == "failed":
            return ExecutionResult(
                status="blocked",
                executor_name="docs+repair",
                summary=f"QA failed: {qa_result.summary}",
                detail_codes=("qa_failed",),
                quality="degraded",
            )
        return synthesis_result

    def synthesis_artifacts_ready(self, execution_result):
        return True

    def execute_publish_plan(self, intake, plan, *, publish, run_dir=None):
        return PublishResult(
            status="dry_run",
            target=plan.status,
            summary="dry_run (test)",
            url=None,
        )

    def run_post_publish_review_if_needed(self, **kwargs):
        return None


class _StubRepairAdapter:
    """Trivial repair adapter that makes a minor change."""

    def __init__(self) -> None:
        self.binary: str | None = None
        self.agent: str | None = None
        self.model: str | None = None
        self.qa_feedback: str | None = None

    def repair(self, *, intake, run_record, run_dir, contract_artifact_dir, repo_workspace):
        from precision_squad.models import RepairResult

        return RepairResult(
            status="completed",
            summary="Stub repair completed.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repo_workspace.parent),
        )

    def with_qa_feedback(self, feedback: str):
        return self
