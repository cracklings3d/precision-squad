"""Tests for filesystem-backed run persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad.models import (
    ApprovedPlan,
    EvaluationResult,
    ExecutionResult,
    GitHubIssue,
    GovernanceVerdict,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    PublishPlan,
    PublishResult,
    QaResult,
    RunRequest,
)
from precision_squad.run_store import (
    ApprovedPlanNotFoundError,
    ApprovedPlanValidationError,
    RunStore,
    load_approved_plan_artifact,
)


def _approved_plan() -> ApprovedPlan:
    return ApprovedPlan(
        issue_ref="owner/repo#1",
        plan_summary="Fix the bug with a minimal change.",
        implementation_steps=("Update the implementation",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )


def test_create_run_writes_expected_artifacts(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    request = RunRequest(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=str(tmp_path / "runs"),
    )
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
            comments=("Reviewer says use exact output.",),
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    record = store.create_run(request, intake)

    run_dir = Path(record.run_dir)
    assert run_dir.exists()
    assert (run_dir / "run-request.json").exists()
    assert (run_dir / "issue-intake.json").exists()
    assert (run_dir / "issue.md").exists()
    assert (run_dir / "run-record.json").exists()

    saved_record = json.loads((run_dir / "run-record.json").read_text(encoding="utf-8"))
    assert saved_record["issue_ref"] == request.issue_ref
    assert saved_record["status"] == "runnable"
    issue_context = (run_dir / "issue.md").read_text(encoding="utf-8")
    assert "## Issue Comments" in issue_context
    assert "Reviewer says use exact output." in issue_context


def test_write_execution_result_persists_json(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    result = ExecutionResult(
        status="blocked",
        executor_name="docs",
        summary="Executor wiring is not implemented yet.",
        detail_codes=("executor_not_implemented",),
    )

    store.write_execution_result(run_dir, result)

    saved_result = json.loads((run_dir / "execution-result.json").read_text(encoding="utf-8"))
    assert saved_result["status"] == "blocked"
    assert saved_result["executor_name"] == "docs"


def test_write_follow_on_artifacts_persists_json(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    evaluation = EvaluationResult(
        status="blocked",
        summary="Execution blocked.",
        detail_codes=("executor_not_implemented",),
    )
    verdict = GovernanceVerdict(
        status="blocked",
        summary="Execution blocked.",
        reason_codes=("executor_not_implemented",),
    )
    plan = PublishPlan(
        status="issue_comment",
        title="Blocked: Add --version flag to CLI",
        body="Blocked body",
        reason_codes=("executor_not_implemented",),
    )

    store.write_evaluation_result(run_dir, evaluation)
    store.write_governance_verdict(run_dir, verdict)
    store.write_publish_plan(run_dir, plan)
    store.write_publish_result(
        run_dir,
        PublishResult(
            status="dry_run",
            target="issue_comment",
            summary="Dry run only.",
            url=None,
        ),
    )

    assert (run_dir / "evaluation-result.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert (run_dir / "publish-plan.json").exists()
    assert (run_dir / "publish-result.json").exists()


def test_write_qa_results_uses_phase_specific_filenames(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    store.write_qa_result(
        run_dir,
        QaResult(
            status="failed",
            summary="Baseline failed.",
            detail_codes=("qa_failed",),
            phase="baseline",
        ),
    )
    store.write_qa_result(
        run_dir,
        QaResult(
            status="passed",
            summary="Final passed.",
            detail_codes=("qa_passed",),
            phase="final",
        ),
    )

    assert (run_dir / "qa-baseline-result.json").exists()
    assert (run_dir / "qa-result.json").exists()


def test_load_approved_plan_rejects_unapproved_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "approved-plan.json").write_text(
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

    with pytest.raises(ApprovedPlanValidationError, match="approved.*true"):
        RunStore.load_approved_plan(run_dir, issue_ref="owner/repo#1")


def test_load_approved_plan_requires_named_references_and_retrieval_surface_summary(tmp_path: Path) -> None:
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Plan",
                "implementation_steps": ["Step 1"],
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ApprovedPlanValidationError, match="named_references"):
        load_approved_plan_artifact(plan_path, issue_ref="owner/repo#1")


def test_load_approved_plan_rejects_non_object_payload(tmp_path: Path) -> None:
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ApprovedPlanValidationError, match="Expected JSON object"):
        load_approved_plan_artifact(plan_path, issue_ref="owner/repo#1")


def test_load_approved_plan_accepts_explicit_empty_canonical_fields(tmp_path: Path) -> None:
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Plan",
                "implementation_steps": ["Step 1"],
                "named_references": [],
                "retrieval_surface_summary": "",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    plan = load_approved_plan_artifact(plan_path, issue_ref="owner/repo#1")

    assert plan.named_references == ()
    assert plan.retrieval_surface_summary == ""


def test_write_approved_plan_normalizes_named_reference_objects(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    plan = load_approved_plan_artifact(
        _write_plan(
            tmp_path / "incoming-approved-plan.json",
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Plan",
                "implementation_steps": ["Step 1"],
                "named_references": ["src/main.py"],
                "retrieval_surface_summary": "src/",
                "approved": True,
            },
        ),
        issue_ref="owner/repo#1",
    )

    store.write_approved_plan(run_dir, plan)

    payload = json.loads((run_dir / "approved-plan.json").read_text(encoding="utf-8"))
    assert payload["named_references"] == [
        {"name": "src/main.py", "reference_type": "file", "description": ""}
    ]


def test_load_approved_plan_missing_artifact_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(ApprovedPlanNotFoundError, match="Approved plan artifact not found"):
        RunStore.load_approved_plan(tmp_path / "missing-run", issue_ref="owner/repo#1")


def test_render_approved_plan_text(tmp_path: Path) -> None:
    del tmp_path
    from precision_squad.run_store import render_approved_plan_text

    text = render_approved_plan_text(_approved_plan(), include_named_references=False)

    assert "Approved Plan" in text
    assert "Fix the bug with a minimal change." in text
    assert "Update the implementation" in text
    assert "Retrieval Surface" in text


def _write_plan(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
