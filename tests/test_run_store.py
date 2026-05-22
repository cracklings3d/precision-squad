"""Tests for filesystem-backed run persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

import pytest

from precision_squad.coordinator import PersistApprovedPlanParams, RunCoordinator
from precision_squad.models import (
    ApprovedPlan,
    DecisionLogArtifact,
    DesignDecision,
    EvaluationResult,
    ExecutionResult,
    GitHubIssue,
    GovernanceVerdict,
    ImplReviewFeedback,
    ImplReviewResult,
    IssueAssessment,
    IssueDraft,
    IssueIntake,
    IssueReference,
    IssueReview,
    IssueReviewFeedback,
    IssueReviewProvenance,
    PlanReview,
    PlanReviewFeedback,
    PlanReviewProvenance,
    PublishPlan,
    PublishResult,
    QaResult,
    RunRequest,
)
from precision_squad.run_store import (
    ApprovedPlanGateError,
    ApprovedPlanNotFoundError,
    ApprovedPlanValidationError,
    IssueReviewNotFoundError,
    IssueReviewValidationError,
    PlanReviewNotApprovedError,
    PlanReviewNotFoundError,
    PlanReviewValidationError,
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


def _issue_review(
    *, status: Literal["approved", "changes_requested", "blocked"] = "approved"
) -> IssueReview:
    feedback = ()
    if status != "approved":
        feedback = (
            IssueReviewFeedback(
                code="missing_summary",
                message="Summary is required.",
                artifact="issue-draft.json",
                field="summary",
            ),
        )
    return IssueReview(
        run_id="run-123",
        issue_ref="owner/repo#1",
        review_status=cast(Literal["approved", "changes_requested", "blocked"], status),
        summary="Planning may proceed because issue-draft.json passed the local planner-safety review."
        if status == "approved"
        else "Planning must stop because issue-draft.json has 1 planner-safety finding that require changes.",
        feedback=feedback,
        provenance=IssueReviewProvenance(
            source_artifact="issue-draft.json",
            run_id="run-123",
            issue_ref="owner/repo#1",
        ),
    )


def _plan_review(
    *, status: Literal["approved", "changes_requested", "blocked"] = "approved"
) -> PlanReview:
    feedback = ()
    if status != "approved":
        feedback = (
            PlanReviewFeedback(
                code="missing_retrieval_surface_summary",
                message="Retrieval surface summary is required.",
                artifact="approved-plan.json",
                field="retrieval_surface_summary",
            ),
        )
    return PlanReview(
        run_id="run-123",
        issue_ref="owner/repo#1",
        review_status=cast(Literal["approved", "changes_requested", "blocked"], status),
        summary="Implementation may proceed because approved-plan.json passed the same-run plan review gate."
        if status == "approved"
        else "Implementation must stop because approved-plan.json has 1 implementation-ingress finding that require changes.",
        feedback=feedback,
        provenance=PlanReviewProvenance(
            source_artifact="approved-plan.json",
            run_id="run-123",
            issue_ref="owner/repo#1",
        ),
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
    assert (run_dir / "issue-draft.json").exists()
    assert (run_dir / "issue.md").exists()
    assert (run_dir / "run-record.json").exists()

    saved_record = json.loads((run_dir / "run-record.json").read_text(encoding="utf-8"))
    assert saved_record["issue_ref"] == request.issue_ref
    assert saved_record["status"] == "runnable"
    issue_context = (run_dir / "issue.md").read_text(encoding="utf-8")
    assert "## Issue Comments" in issue_context
    assert "Reviewer says use exact output." in issue_context


def test_load_issue_draft_reads_normalized_handoff_artifact(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    request = RunRequest(issue_ref="owner/repo#1", runs_dir=str(tmp_path / "runs"))
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Issue title",
            body="Issue body",
            labels=("bug", "backend"),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Issue title",
        problem_statement="Issue body",
        assessment=IssueAssessment(status="blocked", reason_codes=("issue_marked_as_plan",)),
    )

    record = store.create_run(request, intake)

    draft = store.load_issue_draft(record.run_id)

    assert isinstance(draft, IssueDraft)
    assert draft.issue_ref == "owner/repo#1"
    assert draft.labels == ("bug", "backend")
    assert draft.intake_status == "blocked"
    assert draft.intake_reason_codes == ("issue_marked_as_plan",)
    assert draft.provenance.source_artifacts == ("run-request.json", "issue-intake.json")


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


def test_write_and_load_issue_review_persists_same_run_artifact(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    store.write_issue_review(run_dir, _issue_review())

    loaded = store.load_issue_review(run_dir, issue_ref="owner/repo#1")
    payload = json.loads((run_dir / "issue-review.json").read_text(encoding="utf-8"))
    assert loaded == _issue_review()
    assert payload["review_status"] == "approved"
    assert payload["provenance"]["source_artifact"] == "issue-draft.json"


def test_write_and_load_plan_review_persists_same_run_artifact(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    store.write_plan_review(run_dir, _plan_review())

    loaded = store.load_plan_review(run_dir, issue_ref="owner/repo#1")
    payload = json.loads((run_dir / "plan-review.json").read_text(encoding="utf-8"))
    assert loaded == _plan_review()
    assert payload["review_status"] == "approved"
    assert payload["provenance"]["source_artifact"] == "approved-plan.json"


def test_write_and_load_impl_review_persists_canonical_artifact(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    review = ImplReviewResult(
        review_status="changes_requested",
        summary="Published PR requires changes.",
        pull_request_url="https://github.com/owner/repo/pull/1",
        pull_number=1,
        pull_head_sha="abc123",
        feedback=(
            ImplReviewFeedback(
                code="reviewer_changes_requested",
                message="Fix the implementation.",
                source="reviewer",
            ),
        ),
        reviewer_status="rejected",
        reviewer_summary="Reviewer requested changes.",
        architect_status="approved",
        architect_summary="Architect approved.",
        issue_comment_url="comment-url",
        issue_reopened=True,
    )

    store.write_impl_review(run_dir, review)

    loaded = store.load_impl_review(run_dir)
    payload = json.loads((run_dir / "impl-review.json").read_text(encoding="utf-8"))
    assert loaded == review
    assert payload["review_status"] == "changes_requested"
    assert payload["feedback"][0]["source"] == "reviewer"


def test_load_plan_review_missing_artifact_raises_not_found(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    with pytest.raises(PlanReviewNotFoundError, match="Plan review artifact not found"):
        RunStore.load_plan_review(run_dir, issue_ref="owner/repo#1")


def test_require_plan_review_for_implement_requires_run_record_and_approved_review(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    _write_run_record(run_dir)
    store.write_plan_review(run_dir, _plan_review())

    review = RunStore.require_plan_review_for_implement(run_dir, issue_ref="owner/repo#1")

    assert review.review_status == "approved"


@pytest.mark.parametrize(
    ("writer", "match"),
    [
        (None, r"run-record\.json"),
        ("{not-json", r"valid JSON"),
    ],
)
def test_require_plan_review_for_implement_normalizes_missing_or_malformed_run_record(
    tmp_path: Path, writer: str | None, match: str
) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    if writer is not None:
        (run_dir / "run-record.json").write_text(writer, encoding="utf-8")
    store.write_plan_review(run_dir, _plan_review())

    with pytest.raises(PlanReviewValidationError, match=match):
        RunStore.require_plan_review_for_implement(run_dir, issue_ref="owner/repo#1")


@pytest.mark.parametrize("status", ["changes_requested", "blocked"])
def test_require_plan_review_for_implement_rejects_non_approved_status(
    tmp_path: Path, status: Literal["changes_requested", "blocked"]
) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    _write_run_record(run_dir)
    store.write_plan_review(run_dir, _plan_review(status=status))

    with pytest.raises(PlanReviewNotApprovedError, match="review_status"):
        RunStore.require_plan_review_for_implement(run_dir, issue_ref="owner/repo#1")


def test_require_plan_review_for_implement_rejects_invalid_provenance(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    _write_run_record(run_dir)
    payload = {
        "run_id": "run-123",
        "issue_ref": "owner/repo#1",
        "review_status": "approved",
        "summary": "Implementation may proceed because approved-plan.json passed the same-run plan review gate.",
        "feedback": [],
        "provenance": {
            "source_artifact": "issue-review.json",
            "run_id": "run-123",
            "issue_ref": "owner/repo#1",
        },
    }
    (run_dir / "plan-review.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PlanReviewValidationError, match="source_artifact"):
        RunStore.require_plan_review_for_implement(run_dir, issue_ref="owner/repo#1")


def test_load_issue_review_missing_artifact_raises_not_found(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    with pytest.raises(IssueReviewNotFoundError, match="Issue review artifact not found"):
        RunStore.load_issue_review(run_dir, issue_ref="owner/repo#1")


def test_write_gated_approved_plan_requires_issue_review_artifact(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    with pytest.raises(ApprovedPlanGateError, match="requires issue-review.json"):
        store.write_gated_approved_plan(run_dir, _approved_plan())


@pytest.mark.parametrize("status", ["changes_requested", "blocked"])
def test_write_gated_approved_plan_rejects_non_approved_issue_review(
    tmp_path: Path, status: Literal["changes_requested", "blocked"]
) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    store.write_issue_review(run_dir, _issue_review(status=status))

    with pytest.raises(ApprovedPlanGateError, match="review_status"):
        store.write_gated_approved_plan(run_dir, _approved_plan())


def test_write_gated_approved_plan_allows_approved_issue_review(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    store.write_issue_review(run_dir, _issue_review())

    store.write_gated_approved_plan(run_dir, _approved_plan())

    payload = json.loads((run_dir / "approved-plan.json").read_text(encoding="utf-8"))
    assert payload["issue_ref"] == "owner/repo#1"


def _write_run_record(run_dir: Path, *, run_id: str = "run-123", issue_ref: str = "owner/repo#1") -> None:
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "issue_ref": issue_ref,
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )


def test_planning_persistence_rejects_approved_issue_review_with_mismatched_run_id(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    _write_run_record(run_dir)
    payload = {
        "run_id": "run-other",
        "issue_ref": "owner/repo#1",
        "review_status": "approved",
        "summary": "Planning may proceed because issue-draft.json passed the local planner-safety review.",
        "feedback": [],
        "provenance": {
            "source_artifact": "issue-draft.json",
            "run_id": "run-other",
            "issue_ref": "owner/repo#1",
        },
    }
    (run_dir / "issue-review.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(IssueReviewValidationError, match="expected run_id 'run-123'"):
        RunCoordinator().persist_approved_plan_for_planning(
            params=PersistApprovedPlanParams(
                run_id="run-123",
                runs_dir=runs_dir,
                approved_plan=_approved_plan(),
            )
        )


def test_planning_persistence_rejects_approved_issue_review_with_invalid_provenance_source(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    _write_run_record(run_dir)
    payload = {
        "run_id": "run-123",
        "issue_ref": "owner/repo#1",
        "review_status": "approved",
        "summary": "Planning may proceed because issue-draft.json passed the local planner-safety review.",
        "feedback": [],
        "provenance": {
            "source_artifact": "issue-intake.json",
            "run_id": "run-123",
            "issue_ref": "owner/repo#1",
        },
    }
    (run_dir / "issue-review.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(IssueReviewValidationError, match="source_artifact"):
        RunCoordinator().persist_approved_plan_for_planning(
            params=PersistApprovedPlanParams(
                run_id="run-123",
                runs_dir=runs_dir,
                approved_plan=_approved_plan(),
            )
        )


def test_planning_persistence_rejects_malformed_but_approved_issue_review_artifact(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    _write_run_record(run_dir)
    payload = {
        "run_id": "run-123",
        "issue_ref": "owner/repo#1",
        "review_status": "approved",
        "summary": "Planning may proceed because issue-draft.json passed the local planner-safety review.",
        "feedback": "not-a-list",
        "provenance": {
            "source_artifact": "issue-draft.json",
            "run_id": "run-123",
            "issue_ref": "owner/repo#1",
        },
    }
    (run_dir / "issue-review.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(IssueReviewValidationError, match="feedback"):
        RunCoordinator().persist_approved_plan_for_planning(
            params=PersistApprovedPlanParams(
                run_id="run-123",
                runs_dir=runs_dir,
                approved_plan=_approved_plan(),
            )
        )


def test_planning_persistence_helper_requires_review_approval(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    _write_run_record(run_dir)
    RunStore(runs_dir).write_issue_review(run_dir, _issue_review())

    path = RunCoordinator().persist_approved_plan_for_planning(
        params=PersistApprovedPlanParams(
            run_id="run-123",
            runs_dir=runs_dir,
            approved_plan=_approved_plan(),
        )
    )

    assert path == run_dir / "approved-plan.json"
    assert path.exists()


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


def test_write_and_load_decision_log_uses_attempt_scoped_filename(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    artifact = DecisionLogArtifact(
        attempt=2,
        entries=(
            DesignDecision(
                sequence=1,
                summary="Keep decision-log persistence in coordinator",
                rationale="Publishing must load persisted evidence rather than transient state.",
                plan_steps=("Persist decision-log artifact before publish-plan construction",),
                named_references=("src/precision_squad/coordinator.py",),
                affected_targets=("src/precision_squad/coordinator.py",),
            ),
        ),
    )

    store.write_decision_log(run_dir, artifact)

    saved_path = run_dir / "decision-log.attempt-2.json"
    assert saved_path.exists()
    loaded = store.load_decision_log(run_dir, attempt=2)
    assert loaded == artifact


def test_write_decision_log_preserves_prior_attempt_files(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    store.write_decision_log(
        run_dir,
        DecisionLogArtifact(
            attempt=1,
            entries=(
                DesignDecision(
                    sequence=1,
                    summary="Attempt one choice",
                    rationale="First attempt rationale.",
                ),
            ),
        ),
    )
    first_payload = (run_dir / "decision-log.attempt-1.json").read_text(encoding="utf-8")

    store.write_decision_log(
        run_dir,
        DecisionLogArtifact(
            attempt=2,
            entries=(
                DesignDecision(
                    sequence=1,
                    summary="Attempt two choice",
                    rationale="Second attempt rationale.",
                ),
            ),
        ),
    )

    assert (run_dir / "decision-log.attempt-1.json").read_text(encoding="utf-8") == first_payload
    assert (run_dir / "decision-log.attempt-2.json").exists()


def test_write_decision_log_persists_explicit_empty_entries(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-123"
    run_dir.mkdir(parents=True)

    store.write_decision_log(run_dir, DecisionLogArtifact(attempt=1, entries=()))

    payload = json.loads((run_dir / "decision-log.attempt-1.json").read_text(encoding="utf-8"))
    assert payload == {"attempt": 1, "entries": []}


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


def test_list_runs_for_issue_filters_by_canonical_issue_and_orders_newest_first(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.root.mkdir(parents=True)

    same_issue_old = store.root / "run-old"
    same_issue_old.mkdir()
    (same_issue_old / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-old",
                "issue_ref": "Owner/Repo#1",
                "status": "runnable",
                "created_at": "2026-05-02T00:00:00Z",
                "updated_at": "2026-05-02T00:00:00Z",
                "run_dir": str(same_issue_old),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )

    same_issue_new = store.root / "run-new"
    same_issue_new.mkdir()
    (same_issue_new / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-new",
                "issue_ref": "owner/repo#1",
                "status": "blocked",
                "created_at": "2026-05-02T00:00:00Z",
                "updated_at": "2026-05-02T00:00:00Z",
                "run_dir": str(same_issue_new),
                "attempt": 2,
            }
        ),
        encoding="utf-8",
    )

    different_issue = store.root / "run-other"
    different_issue.mkdir()
    (different_issue / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-other",
                "issue_ref": "owner/repo#2",
                "status": "runnable",
                "created_at": "2026-05-03T00:00:00Z",
                "updated_at": "2026-05-03T00:00:00Z",
                "run_dir": str(different_issue),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )

    records = store.list_runs_for_issue("owner/repo#1")

    assert [record.run_id for record in records] == ["run-new", "run-old"]


def _write_plan(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
