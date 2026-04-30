"""Tests for evaluation, governance, and publishing."""

from __future__ import annotations

from precision_squad.governance import apply_governance, evaluate_run
from precision_squad.models import (
    ExecutionResult,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RunRecord,
)
from precision_squad.publishing import build_publish_plan


def _bounded_intake() -> IssueIntake:
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


def _plan_intake() -> IssueIntake:
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 1),
            title="[Plan] Markdown to PDF Renderer",
            body="## Project Plan",
            labels=("plan",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/1",
        ),
        summary="Markdown to PDF Renderer",
        problem_statement="Project plan",
        assessment=IssueAssessment(status="blocked", reason_codes=("issue_marked_as_plan",)),
    )


def _run_record() -> RunRecord:
    return RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-26T00:00:00Z",
        updated_at="2026-04-26T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )


def test_evaluate_run_maps_completed_to_success() -> None:
    evaluation = evaluate_run(
        _bounded_intake(),
        ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Execution completed.",
            detail_codes=(),
        ),
    )

    assert evaluation.status == "success"


def test_evaluate_run_maps_missing_docs_to_blocked() -> None:
    evaluation = evaluate_run(
        _bounded_intake(),
        ExecutionResult(
            status="missing_docs",
            executor_name="docs",
            summary="Missing setup and QA docs.",
            detail_codes=("docs_missing",),
        ),
    )

    assert evaluation.status == "blocked"


def test_evaluate_run_maps_ambiguous_docs_to_blocked() -> None:
    evaluation = evaluate_run(
        _bounded_intake(),
        ExecutionResult(
            status="ambiguous_docs",
            executor_name="docs",
            summary="Conflicting setup docs.",
            detail_codes=("docs_ambiguous",),
        ),
    )

    assert evaluation.status == "blocked"


def test_apply_governance_blocks_plan_issue_without_execution() -> None:
    verdict = apply_governance(_plan_intake(), execution_result=None, evaluation_result=None)

    assert verdict.status == "blocked"
    assert "issue_marked_as_plan" in verdict.reason_codes


def test_apply_governance_approves_successful_run() -> None:
    intake = _bounded_intake()
    execution = ExecutionResult(
        status="completed",
        executor_name="docs",
        summary="Execution completed.",
        detail_codes=(),
    )
    evaluation = evaluate_run(intake, execution)

    verdict = apply_governance(intake, execution, evaluation)

    assert verdict.status == "approved"


def test_apply_governance_approves_run_with_baseline_improved_detail_code() -> None:
    intake = _bounded_intake()
    execution = ExecutionResult(
        status="completed",
        executor_name="docs+repair",
        summary="Execution completed with baseline-tolerant QA.",
        detail_codes=("repair_stage_completed", "qa_baseline_improved"),
        quality="improved",
    )
    evaluation = evaluate_run(intake, execution)

    verdict = apply_governance(intake, execution, evaluation)

    assert verdict.status == "approved"
    assert verdict.reason_codes == ("qa_baseline_improved",)


def test_apply_governance_approves_run_with_approximated_qa_detail_code() -> None:
    intake = _bounded_intake()
    execution = ExecutionResult(
        status="completed",
        executor_name="docs+repair",
        summary="Execution completed with approximated QA.",
        detail_codes=("repair_stage_completed", "qa_approximated"),
    )
    evaluation = evaluate_run(intake, execution)

    verdict = apply_governance(intake, execution, evaluation)

    assert verdict.status == "approved"
    assert verdict.reason_codes == ()


def test_apply_governance_blocks_unrunnable_qa_run() -> None:
    intake = _bounded_intake()
    execution = ExecutionResult(
        status="blocked",
        executor_name="docs+repair",
        summary="The documented QA command did not produce a trustworthy verification signal.",
        detail_codes=("repair_stage_completed", "qa_command_unrunnable"),
    )
    evaluation = evaluate_run(intake, execution)

    verdict = apply_governance(intake, execution, evaluation)

    assert verdict.status == "blocked"
    assert verdict.reason_codes == ("repair_stage_completed", "qa_command_unrunnable")


def test_build_publish_plan_returns_issue_comment_for_blocked() -> None:
    verdict = apply_governance(_plan_intake(), execution_result=None, evaluation_result=None)

    plan = build_publish_plan(_plan_intake(), _run_record(), verdict)

    assert plan.status == "issue_comment"
    assert "issue_marked_as_plan" in plan.body


def test_build_publish_plan_returns_follow_up_issue_for_docs_blocker() -> None:
    intake = _bounded_intake()
    execution = ExecutionResult(
        status="missing_docs",
        executor_name="docs",
        summary="Missing documented QA command.",
        detail_codes=("docs_qa_command_missing",),
    )
    evaluation = evaluate_run(intake, execution)

    plan = build_publish_plan(intake, _run_record(), apply_governance(intake, execution, evaluation))

    assert plan.status == "follow_up_issue"
    assert "Source issue URL" in plan.body
    assert "docs_qa_command_missing" in plan.body


def test_build_publish_plan_returns_draft_pr_for_approved() -> None:
    intake = _bounded_intake()
    execution = ExecutionResult(
        status="completed",
        executor_name="docs",
        summary="Execution completed.",
        detail_codes=(),
    )
    evaluation = evaluate_run(intake, execution)
    verdict = apply_governance(intake, execution, evaluation)

    plan = build_publish_plan(intake, _run_record(), verdict)

    assert plan.status == "draft_pr"
    assert "Run ID: `run-123`" in plan.body



