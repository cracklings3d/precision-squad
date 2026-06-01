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
    ApprovedPlan,
    ExecutionResult,
    ImplReviewResult,
    IssueIntake,
    PublishResult,
    RepairResult,
    RunRecord,
)
from precision_squad.repair import RepairAdapter
from tests.integration.support import approved_plan_for

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
    assert report.governance_verdict.verdict == "blocked"
    assert report.publish_plan is not None
    assert report.publish_plan.status == "issue_comment"
    assert report.publish_result is not None
    assert report.publish_result.status == "dry_run"
    assert report.exit_code == 3

    run_dir = Path(report.run_record.run_dir)
    assert (run_dir / "run-request.json").exists()
    assert (run_dir / "issue-intake.json").exists()
    assert (run_dir / "issue-draft.json").exists()
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
    """Missing docs block before publish even with explicit approved plan."""
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
        approved_plan=approved_plan_for(),
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

    assert report.plan_review is not None
    assert report.plan_review.verdict == "approved"
    assert report.execution_result is not None, "explicit approval path should continue into execution"
    assert report.execution_result.status == "missing_docs"
    assert (Path(report.run_record.run_dir) / "approved-plan.json").exists()
    assert (Path(report.run_record.run_dir) / "plan-review.json").exists()
    # Missing docs blocks at governance after execution; publish is not reached.
    assert report.governance_verdict is not None
    assert report.governance_verdict.verdict == "blocked"
    assert report.publish_plan is None
    assert report.publish_result is None
    assert report.exit_code == 4


@pytest.mark.integration
def test_missing_docs_persists_execution_artifacts(
    make_empty_repo,
    tmp_path: Path,
) -> None:
    """Missing-docs runs persist explicit plan and execution artifacts.

    With explicit approved plan, runs materialize approved-plan/plan-review before
    missing docs blocks governance.
    """
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
        approved_plan=approved_plan_for(),
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

    assert report.plan_review is not None
    assert report.plan_review.verdict == "approved"
    assert report.execution_result is not None
    assert report.execution_result.status == "missing_docs"
    assert (run_dir / "approved-plan.json").exists()
    assert (run_dir / "plan-review.json").exists()
    assert (run_dir / "execution-result.json").exists()
    assert (run_dir / "evaluation-result.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert not (run_dir / "repair-result.json").exists()
    assert not (run_dir / "qa-baseline-result.json").exists()
    assert not (run_dir / "qa-result.json").exists()
    assert not (run_dir / "publish-plan.json").exists()
    assert not (run_dir / "publish-result.json").exists()
    assert report.governance_verdict is not None
    assert report.governance_verdict.verdict == "blocked"
    assert report.publish_plan is None
    assert report.publish_result is None
    assert report.exit_code == 4


# ---------------------------------------------------------------------------
# Ambiguous docs: executor runs, finds ambiguous docs, governance blocks
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_ambiguous_docs_blocks_pipeline(
    make_ambiguous_repo,
    tmp_path: Path,
) -> None:
    """Ambiguous docs block before publish even with explicit approved plan.

    With explicit approved plan, the docs executor is reached and ambiguous docs
    trigger a blocked governance verdict.
    """
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
        approved_plan=approved_plan_for(),
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

    assert report.plan_review is not None
    assert report.plan_review.verdict == "approved"
    assert report.execution_result is not None
    assert report.execution_result.status == "ambiguous_docs"
    assert report.governance_verdict is not None
    assert report.governance_verdict.verdict == "blocked"
    assert report.publish_plan is None
    assert report.publish_result is None
    assert report.exit_code == 4


# ---------------------------------------------------------------------------
# Clean docs without repair complete with explicit approved plan
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_clean_docs_without_repair_completes_pipeline(
    make_clean_repo,
    tmp_path: Path,
) -> None:
    """Explicit approved plan reaches dry-run publish on clean docs."""
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
        approved_plan=approved_plan_for(),
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

    assert report.plan_review is not None
    assert report.plan_review.verdict == "approved"
    assert report.execution_result is not None
    assert report.execution_result.status == "completed"
    assert report.repair_result is None
    assert report.qa_result is None
    assert report.governance_verdict is not None
    assert report.governance_verdict.verdict == "approved"
    assert report.publish_plan is not None
    assert report.publish_plan.status == "draft_pr"
    assert report.publish_result is not None
    assert report.publish_result.status == "dry_run"
    assert report.exit_code == 0


# ---------------------------------------------------------------------------
# QA failed: repair completes but QA fails -> blocked verdict, quality=degraded
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_qa_failed_blocks_pipeline(
    make_clean_repo,
    tmp_path: Path,
) -> None:
    """Explicit approved plan allows repair/QA to block governance.

    Repair and QA execute with explicit approved plan and can still block governance.
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

    assert report.plan_review is not None
    assert report.plan_review.verdict == "approved"
    assert report.repair_result is not None, "repair should run with explicit approved plan"
    assert report.qa_result is not None, "QA should run with explicit approved plan"
    assert report.qa_result.status == "failed"
    assert report.execution_result is not None, "implementation result should reflect the QA failure"
    assert report.execution_result.status == "blocked"
    assert report.governance_verdict is not None
    assert report.governance_verdict.verdict == "blocked"
    assert report.publish_plan is None
    assert report.publish_result is None
    assert report.exit_code == 4


# ---------------------------------------------------------------------------
# Test dependencies (blocks executor + all external calls)
# ---------------------------------------------------------------------------

class _BlockedTestDependencies:
    """Replacement dependencies that block all repair and publishing."""

    def create_repair_adapter(
        self, *, repair_agent: str, repair_model: str | None
    ) -> RepairAdapter | None:
        del repair_agent, repair_model
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

    def post_publish_review_is_stale(self, intake, review_result) -> bool:
        del intake, review_result
        return False

    def run_impl_review(self, **kwargs) -> ImplReviewResult:
        raise AssertionError("implementation review should not run for blocked intake")


class _QaFailedTestDependencies:
    """Dependencies that simulate a QA failure after successful repair."""

    def __init__(self) -> None:
        self._adapter = _StubRepairAdapter()

    def create_repair_adapter(
        self, *, repair_agent: str, repair_model: str | None
    ) -> RepairAdapter | None:
        del repair_model
        if repair_agent == "none":
            return None
        return self._adapter

    def run_repair_qa_loop(
        self, *, repo_path, adapter, intake, run_record, run_dir, contract_artifact_dir
    ):
        from precision_squad.models import QaResult

        del adapter, contract_artifact_dir, intake, repo_path, run_record

        repair_workspace = run_dir / "repair-workspace"
        (repair_workspace / "repo").mkdir(parents=True, exist_ok=True)
        (run_dir / "repair.patch").write_text("diff --git a/x b/x\n", encoding="utf-8")

        repair_result = RepairResult(
            status="completed",
            summary="Stub repair completed.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repair_workspace),
            patch_path=str(run_dir / "repair.patch"),
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

    def post_publish_review_is_stale(self, intake, review_result) -> bool:
        del intake, review_result
        return False

    def run_impl_review(self, **kwargs) -> ImplReviewResult:
        raise AssertionError("implementation review should not run for QA-failed run")


class _StubRepairAdapter:
    """Trivial repair adapter that makes a minor change."""

    def __init__(self) -> None:
        self.binary: str | None = None
        self.agent: str | None = None
        self.model: str | None = None
        self.qa_feedback: str | None = None

    def repair(
        self,
        *,
        approved_plan: ApprovedPlan | None = None,
        intake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
        developer_contract: object | None = None,
    ) -> RepairResult:
        del approved_plan, contract_artifact_dir, developer_contract, intake, run_record

        return RepairResult(
            status="completed",
            summary="Stub repair completed.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repo_workspace.parent),
            patch_path=str(run_dir / "repair.patch"),
        )

    def with_qa_feedback(self, feedback: str) -> _StubRepairAdapter:
        self.qa_feedback = feedback
        return self
