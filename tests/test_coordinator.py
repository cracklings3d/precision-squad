"""Focused tests for RunCoordinator bounded workflows."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from precision_squad.coordinator import (
    ImplementRunParams,
    PersistApprovedPlanParams,
    RepairIssueParams,
    ReviewPlanParams,
    RunCoordinator,
)
from precision_squad.models import (
    ApprovedPlan,
    ExecutionResult,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    IssueReview,
    IssueReviewProvenance,
    PlanReview,
    PublishPlan,
    PublishResult,
    QaResult,
    RepairResult,
    RunRequest,
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


def _write_implement_ingress(
    run_dir: Path,
    *,
    run_id: str,
    issue_ref: str = "owner/repo#1",
    review_status: str = "approved",
    provenance_run_id: str | None = None,
    intake_issue_number: int = 1,
    provenance_issue_ref: str | None = None,
) -> None:
    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {"owner": "owner", "repo": "repo", "number": intake_issue_number},
                    "title": "Test issue",
                    "body": "Fix the bug.",
                    "labels": [],
                    "html_url": "https://github.com/owner/repo/issues/1",
                },
                "summary": "Test issue",
                "problem_statement": "Fix the bug.",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "plan-review.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "issue_ref": issue_ref,
                "review_status": review_status,
                "summary": "Implementation may proceed because approved-plan.json passed the same-run plan review gate.",
                "feedback": [],
                "provenance": {
                    "source_artifact": "approved-plan.json",
                    "run_id": provenance_run_id or run_id,
                    "issue_ref": provenance_issue_ref or issue_ref,
                },
            }
        ),
        encoding="utf-8",
    )


def _make_implement_params(tmp_path: Path, run_id: str) -> ImplementRunParams:
    repo_path = tmp_path / "repo"
    repo_path.mkdir(exist_ok=True)
    return ImplementRunParams(
        run_id=run_id,
        runs_dir=tmp_path / "runs",
        repo_path=repo_path,
        repair_agent="none",
        repair_model=None,
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
        workspace_path=str(tmp_path / "repair-workspace"),
        patch_path=str(tmp_path / "repair.patch"),
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
        workspace_path=str(tmp_path / "repair-workspace"),
        patch_path=str(tmp_path / "repair.patch"),
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


def test_implement_run_requires_same_run_approved_review_before_execution(
    tmp_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_approved_plan(run_dir, _approved_plan())

    def fail_if_execute(self, intake, run_record, run_dir):
        raise AssertionError("docs-first execution should not start before implement ingress validates")

    import precision_squad.coordinator as coord_module

    monkeypatch.setattr(coord_module.DocsFirstExecutor, "execute", fail_if_execute)

    with pytest.raises(ValueError, match="Plan review artifact not found"):
        RunCoordinator().implement_run(
            params=_make_implement_params(tmp_path, record.run_id),
            dependencies=MagicMock(),
        )


def test_implement_run_refuses_when_approved_plan_missing(
    tmp_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    _write_implement_ingress(run_dir, run_id=record.run_id)

    def fail_if_execute(self, intake, run_record, run_dir):
        raise AssertionError("docs-first execution should not start before implement ingress validates")

    import precision_squad.coordinator as coord_module

    monkeypatch.setattr(coord_module.DocsFirstExecutor, "execute", fail_if_execute)

    with pytest.raises(ValueError, match="Approved plan artifact not found"):
        RunCoordinator().implement_run(
            params=_make_implement_params(tmp_path, record.run_id),
            dependencies=MagicMock(),
        )


@pytest.mark.parametrize("review_status", ["changes_requested", "blocked"])
def test_implement_run_refuses_when_plan_review_not_approved(
    tmp_path: Path, monkeypatch, review_status: str
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_approved_plan(run_dir, _approved_plan())
    _write_implement_ingress(run_dir, run_id=record.run_id, review_status=review_status)

    def fail_if_execute(self, intake, run_record, run_dir):
        raise AssertionError("docs-first execution should not start before implement ingress validates")

    import precision_squad.coordinator as coord_module

    monkeypatch.setattr(coord_module.DocsFirstExecutor, "execute", fail_if_execute)

    with pytest.raises(ValueError, match="review_status"):
        RunCoordinator().implement_run(
            params=_make_implement_params(tmp_path, record.run_id),
            dependencies=MagicMock(),
        )


def test_implement_run_refuses_when_plan_review_provenance_run_id_mismatches(
    tmp_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_approved_plan(run_dir, _approved_plan())
    _write_implement_ingress(
        run_dir,
        run_id=record.run_id,
        provenance_run_id="run-other",
    )

    def fail_if_execute(self, intake, run_record, run_dir):
        raise AssertionError("docs-first execution should not start before implement ingress validates")

    import precision_squad.coordinator as coord_module

    monkeypatch.setattr(coord_module.DocsFirstExecutor, "execute", fail_if_execute)

    with pytest.raises(ValueError, match="provenance.run_id"):
        RunCoordinator().implement_run(
            params=_make_implement_params(tmp_path, record.run_id),
            dependencies=MagicMock(),
        )


def test_implement_run_refuses_when_issue_intake_issue_ref_mismatches_run_record(
    tmp_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_approved_plan(run_dir, _approved_plan())
    _write_implement_ingress(run_dir, run_id=record.run_id, intake_issue_number=2)

    def fail_if_execute(self, intake, run_record, run_dir):
        raise AssertionError("docs-first execution should not start before implement ingress validates")

    import precision_squad.coordinator as coord_module

    monkeypatch.setattr(coord_module.DocsFirstExecutor, "execute", fail_if_execute)

    with pytest.raises(ValueError, match="issue-intake.json to match the stored run issue_ref"):
        RunCoordinator().implement_run(
            params=_make_implement_params(tmp_path, record.run_id),
            dependencies=MagicMock(),
        )


def test_implement_run_refuses_when_plan_review_issue_ref_mismatches_run_record(
    tmp_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_approved_plan(run_dir, _approved_plan())
    _write_implement_ingress(
        run_dir,
        run_id=record.run_id,
        issue_ref="owner/repo#2",
        provenance_issue_ref="owner/repo#2",
    )

    def fail_if_execute(self, intake, run_record, run_dir):
        raise AssertionError("docs-first execution should not start before implement ingress validates")

    import precision_squad.coordinator as coord_module

    monkeypatch.setattr(coord_module.DocsFirstExecutor, "execute", fail_if_execute)

    with pytest.raises(ValueError, match="does not match expected issue_ref 'owner/repo#1'"):
        RunCoordinator().implement_run(
            params=_make_implement_params(tmp_path, record.run_id),
            dependencies=MagicMock(),
        )


def test_implement_run_persists_local_artifacts_without_publish_side_effects(
    tmp_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_approved_plan(run_dir, _approved_plan())
    _write_implement_ingress(run_dir, run_id=record.run_id)

    execution_result = ExecutionResult(
        status="completed",
        executor_name="docs",
        summary="Execution completed.",
        detail_codes=(),
        artifact_dir=str(run_dir / "execution-contract"),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair completed.",
        detail_codes=("repair_stage_completed",),
        workspace_path=str(tmp_path / "repair-workspace"),
        patch_path=str(tmp_path / "repair.patch"),
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

    dependencies = MagicMock()
    dependencies.synthesis_artifacts_ready.return_value = True
    dependencies.run_repair_qa_loop.return_value = (repair_result, baseline, final)
    dependencies.merge_execution_result.return_value = execution_result

    report = RunCoordinator().implement_run(
        params=_make_implement_params(tmp_path, record.run_id),
        dependencies=dependencies,
    )

    assert report.exit_code == 0
    assert (run_dir / "execution-result.json").exists()
    assert (run_dir / "repair-result.json").exists()
    assert (run_dir / "decision-log.attempt-1.json").exists()
    assert (run_dir / "qa-baseline-result.json").exists()
    assert (run_dir / "qa-result.json").exists()
    assert (run_dir / "evaluation-result.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert not (run_dir / "publish-plan.json").exists()
    assert not (run_dir / "publish-result.json").exists()
    dependencies.execute_publish_plan.assert_not_called()
    dependencies.run_post_publish_review_if_needed.assert_not_called()


def test_persist_approved_plan_for_planning_writes_same_run_artifact(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=record.run_id,
            issue_ref="owner/repo#1",
            review_status="approved",
            summary="Planning may proceed because issue-draft.json passed the local planner-safety review.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=record.run_id,
                issue_ref="owner/repo#1",
            ),
        ),
    )

    path = RunCoordinator().persist_approved_plan_for_planning(
        params=PersistApprovedPlanParams(
            run_id=record.run_id,
            runs_dir=runs_dir,
            approved_plan=_approved_plan(),
        )
    )

    assert path == run_dir / "approved-plan.json"
    assert path.exists()


def test_persist_approved_plan_for_planning_rejects_issue_mismatch(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#2", runs_dir=str(runs_dir)),
        IssueIntake(
            issue=GitHubIssue(
                reference=IssueReference("owner", "repo", 2),
                title="Test issue two",
                body="Fix the other bug.",
                labels=(),
                html_url="https://github.com/owner/repo/issues/2",
            ),
            summary="Test issue two",
            problem_statement="Fix the other bug.",
            assessment=IssueAssessment(status="runnable", reason_codes=()),
        ),
    )

    with pytest.raises(ValueError, match="does not match the stored run issue_ref"):
        RunCoordinator().persist_approved_plan_for_planning(
            params=PersistApprovedPlanParams(
                run_id=record.run_id,
                runs_dir=runs_dir,
                approved_plan=_approved_plan(),
            )
        )


def test_review_plan_persists_same_run_plan_review_artifact(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=record.run_id,
            issue_ref="owner/repo#1",
            review_status="approved",
            summary="Planning may proceed because issue-draft.json passed the local planner-safety review.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=record.run_id,
                issue_ref="owner/repo#1",
            ),
        ),
    )
    store.write_approved_plan(run_dir, _approved_plan())

    report = RunCoordinator().review_plan(
        params=ReviewPlanParams(run_id=record.run_id, runs_dir=runs_dir)
    )

    assert report.exit_code == 0
    assert isinstance(report.plan_review, PlanReview)
    assert report.plan_review.review_status == "approved"
    assert (run_dir / "plan-review.json").exists()


def test_review_plan_returns_changes_requested_for_correctable_plan_findings(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=record.run_id,
            issue_ref="owner/repo#1",
            review_status="approved",
            summary="Planning may proceed because issue-draft.json passed the local planner-safety review.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=record.run_id,
                issue_ref="owner/repo#1",
            ),
        ),
    )
    store.write_approved_plan(
        run_dir,
        ApprovedPlan(
            issue_ref="owner/repo#1",
            plan_summary="Fix the bug with a minimal change.",
            implementation_steps=("Update the implementation",),
            named_references=(),
            retrieval_surface_summary="",
            approved=True,
        ),
    )

    report = RunCoordinator().review_plan(
        params=ReviewPlanParams(run_id=record.run_id, runs_dir=runs_dir)
    )

    assert report.exit_code == 2
    assert report.plan_review.review_status == "changes_requested"
    assert report.plan_review.feedback[0].code == "missing_retrieval_surface_summary"


@pytest.mark.parametrize(
    ("approved_plan_payload", "expected_code", "expected_exit_code"),
    [
        (
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "",
                "implementation_steps": ["Update the implementation"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            },
            "missing_plan_summary",
            2,
        ),
        (
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Fix the bug with a minimal change.",
                "implementation_steps": ["   "],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            },
            "missing_implementation_steps",
            2,
        ),
        (
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Fix the bug with a minimal change.",
                "implementation_steps": [],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            },
            "missing_implementation_steps",
            2,
        ),
        (
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Fix the bug with a minimal change.",
                "implementation_steps": ["Step 1", "   "],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            },
            "missing_implementation_steps",
            2,
        ),
        (
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Fix the bug with a minimal change.",
                "implementation_steps": ["Update the implementation"],
                "named_references": [],
                "retrieval_surface_summary": " ",
                "approved": True,
            },
            "missing_retrieval_surface_summary",
            2,
        ),
    ],
)
def test_review_plan_returns_changes_requested_for_required_implementation_safety_defects(
    tmp_path: Path,
    approved_plan_payload: dict[str, object],
    expected_code: str,
    expected_exit_code: int,
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=record.run_id,
            issue_ref="owner/repo#1",
            review_status="approved",
            summary="Planning may proceed because issue-draft.json passed the local planner-safety review.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=record.run_id,
                issue_ref="owner/repo#1",
            ),
        ),
    )
    (run_dir / "approved-plan.json").write_text(
        json.dumps(approved_plan_payload),
        encoding="utf-8",
    )

    report = RunCoordinator().review_plan(
        params=ReviewPlanParams(run_id=record.run_id, runs_dir=runs_dir)
    )

    assert report.exit_code == expected_exit_code
    assert report.plan_review.review_status == "changes_requested"
    assert report.plan_review.feedback[0].code == expected_code


def test_review_plan_returns_blocked_for_non_string_implementation_step_even_with_valid_ordering(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=record.run_id,
            issue_ref="owner/repo#1",
            review_status="approved",
            summary="Planning may proceed because issue-draft.json passed the local planner-safety review.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=record.run_id,
                issue_ref="owner/repo#1",
            ),
        ),
    )
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Fix the bug with a minimal change.",
                "implementation_steps": ["Step 1", 2],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    report = RunCoordinator().review_plan(
        params=ReviewPlanParams(run_id=record.run_id, runs_dir=runs_dir)
    )

    assert report.exit_code == 3
    assert report.plan_review.review_status == "blocked"
    assert report.plan_review.feedback[0].code == "approved_plan_invalid"
    assert "implementation_steps[2] must be a string" in report.plan_review.feedback[0].message


def test_review_plan_returns_blocked_when_prerequisite_issue_review_missing(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_approved_plan(run_dir, _approved_plan())

    report = RunCoordinator().review_plan(
        params=ReviewPlanParams(run_id=record.run_id, runs_dir=runs_dir)
    )

    assert report.exit_code == 3
    assert report.plan_review.review_status == "blocked"
    assert report.plan_review.feedback[0].code == "issue_review_missing"


def test_review_plan_returns_blocked_when_schema_invalid_plan_also_has_change_level_findings(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    record = store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)),
        _make_intake(),
    )
    run_dir = Path(record.run_dir)
    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=record.run_id,
            issue_ref="owner/repo#1",
            review_status="approved",
            summary="Planning may proceed because issue-draft.json passed the local planner-safety review.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=record.run_id,
                issue_ref="owner/repo#1",
            ),
        ),
    )
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Fix the bug with a minimal change.",
                "implementation_steps": ["Update the implementation"],
                "retrieval_surface_summary": "",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    report = RunCoordinator().review_plan(
        params=ReviewPlanParams(run_id=record.run_id, runs_dir=runs_dir)
    )

    assert report.exit_code == 3
    assert report.plan_review.review_status == "blocked"
    assert report.plan_review.feedback[0].code == "approved_plan_invalid"
    assert "named_references" in report.plan_review.feedback[0].message
