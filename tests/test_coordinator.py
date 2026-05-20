"""Focused tests for decision-log persistence in RunCoordinator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    ApprovedPlan,
    ExecutionResult,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    PublishPlan,
    PublishResult,
    QaResult,
    RepairResult,
)
from precision_squad.run_store import RunStore


def _approved_plan() -> ApprovedPlan:
    return ApprovedPlan(
        issue_ref="owner/repo#1",
        plan_summary="Fix the bug with a minimal change.",
        implementation_steps=("Update the implementation",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )


def _make_intake() -> IssueIntake:
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
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )


def _make_params(tmp_path: Path) -> RepairIssueParams:
    repo_path = tmp_path / "repo"
    repo_path.mkdir(exist_ok=True)
    return RepairIssueParams(
        issue_ref="owner/repo#1",
        runs_dir=tmp_path / "runs",
        repo_path=repo_path,
        publish=False,
        repair_agent="none",
        repair_model=None,
        review_model=None,
        approved_plan=_approved_plan(),
    )


def test_repair_issue_persists_empty_decision_log_before_publish(tmp_path: Path, monkeypatch) -> None:
    execution_result = ExecutionResult(
        status="completed",
        executor_name="test",
        summary="Execution completed.",
        detail_codes=(),
        artifact_dir=str(tmp_path / "artifacts"),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair completed.",
        detail_codes=("repair_stage_completed",),
        design_decisions=(),
    )
    baseline = QaResult(status="passed", summary="Baseline passed.", detail_codes=(), phase="baseline")
    final = QaResult(status="passed", summary="Final passed.", detail_codes=(), phase="final")

    import precision_squad.coordinator as coord_module

    monkeypatch.setattr(
        coord_module.DocsFirstExecutor,
        "execute",
        lambda self, intake, run_record, run_dir: execution_result,
    )

    captured_run_dir: Path | None = None
    captured_plan: PublishPlan | None = None

    def execute_publish_plan(intake, plan, *, publish, run_dir=None):
        nonlocal captured_run_dir, captured_plan
        captured_run_dir = run_dir
        captured_plan = plan
        assert run_dir is not None
        payload = RunStore(tmp_path / "runs").load_decision_log(run_dir, attempt=1)
        assert payload.entries == ()
        return PublishResult(status="dry_run", target=plan.status, summary="Dry run", url=None)

    dependencies = MagicMock()
    dependencies.synthesis_artifacts_ready.return_value = True
    dependencies.run_repair_qa_loop.return_value = (repair_result, baseline, final)
    dependencies.merge_execution_result.return_value = execution_result
    dependencies.execute_publish_plan.side_effect = execute_publish_plan
    dependencies.run_post_publish_review_if_needed.return_value = None

    report = RunCoordinator().repair_issue(
        params=_make_params(tmp_path),
        intake=_make_intake(),
        dependencies=dependencies,
    )

    run_dir = Path(report.run_record.run_dir)
    assert (run_dir / "decision-log.attempt-1.json").exists()
    assert captured_run_dir == run_dir
    assert captured_plan is not None
    assert "## Design Decisions" not in captured_plan.body


def test_repair_issue_marks_missing_decision_log_artifact_as_failed_infra(
    tmp_path: Path, monkeypatch
) -> None:
    execution_result = ExecutionResult(
        status="completed",
        executor_name="test",
        summary="Execution completed.",
        detail_codes=(),
        artifact_dir=str(tmp_path / "artifacts"),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair completed.",
        detail_codes=("repair_stage_completed",),
    )
    baseline = QaResult(status="passed", summary="Baseline passed.", detail_codes=(), phase="baseline")
    final = QaResult(status="passed", summary="Final passed.", detail_codes=(), phase="final")

    import precision_squad.coordinator as coord_module

    monkeypatch.setattr(
        coord_module.DocsFirstExecutor,
        "execute",
        lambda self, intake, run_record, run_dir: execution_result,
    )
    monkeypatch.setattr(coord_module.RunStore, "write_decision_log", lambda self, run_dir, artifact: None)

    dependencies = MagicMock()
    dependencies.synthesis_artifacts_ready.return_value = True
    dependencies.run_repair_qa_loop.return_value = (repair_result, baseline, final)
    dependencies.merge_execution_result.return_value = execution_result
    dependencies.execute_publish_plan.return_value = PublishResult(
        status="dry_run",
        target="issue_comment",
        summary="Dry run",
        url=None,
    )
    dependencies.run_post_publish_review_if_needed.return_value = None

    report = RunCoordinator().repair_issue(
        params=_make_params(tmp_path),
        intake=_make_intake(),
        dependencies=dependencies,
    )

    assert report.execution_result is not None
    assert report.execution_result.status == "failed_infra"
    assert "missing_decision_log_artifact" in report.execution_result.detail_codes
    assert report.governance_verdict is not None
    assert report.governance_verdict.status == "blocked"
    assert report.publish_plan is not None
    assert report.publish_plan.status == "issue_comment"
