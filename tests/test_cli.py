"""Tests for the bootstrap CLI surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad import __version__
from precision_squad.bootstrap import main as bootstrap_main
from precision_squad.cli import (
    _REPAIR_AGENT_CHOICES,
    _build_repair_adapter,
    _CliRepairDependencies,
    _prompt_for_run_selection,
    _repair_issue_prompt_is_interactive,
    main,
)
from precision_squad.coordinator import RepairIssueReport
from precision_squad.models import (
    ApprovedPlan,
    EvaluationResult,
    ExecutionResult,
    GitHubIssue,
    GovernanceVerdict,
    ImplReviewFeedback,
    ImplReviewResult,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    IssueReview,
    IssueReviewFeedback,
    IssueReviewProvenance,
    PlanReview,
    PlanReviewFeedback,
    PlanReviewProvenance,
    PostPublishReviewResult,
    PublishPlan,
    PublishResult,
    RunRecord,
    RunRequest,
)
from precision_squad.repair import (
    OpenCodeRepairAdapter,
    RepairAdapter,
    VercelAIRepairAdapter,
)
from precision_squad.run_store import RunStore


def test_main_without_args_shows_help(capsys) -> None:
    status = main([])

    captured = capsys.readouterr()
    assert status == 0
    assert "precision-squad" in captured.out
    assert "run" in captured.out


def test_create_issue_prints_bounded_issue_preparation_output(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "precision-squad", 67),
            title="Add the create issue stage command",
            body="## Description\nPersist normalized issue handoff artifacts.",
            labels=("enhancement", "workflow"),
            html_url="https://github.com/cracklings3d/precision-squad/issues/67",
        ),
        summary="Add the create issue stage command",
        problem_statement="Persist normalized issue handoff artifacts.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    status = main(
        [
            "create",
            "issue",
            "cracklings3d/precision-squad#67",
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Issue: cracklings3d/precision-squad#67" in captured.out
    assert "Classification: runnable" in captured.out
    assert "issue-draft.json" in captured.out


def test_create_issue_persists_bounded_preparation_artifacts(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "precision-squad", 67),
            title="Add the create issue stage command",
            body="## Description\nPersist normalized issue handoff artifacts.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/precision-squad/issues/67",
        ),
        summary="Add the create issue stage command",
        problem_statement="Persist normalized issue handoff artifacts.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    status = main(
        [
            "create",
            "issue",
            "cracklings3d/precision-squad#67",
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    run_dir_line = next(line for line in captured.out.splitlines() if line.startswith("Run Dir:"))
    run_dir = Path(run_dir_line.removeprefix("Run Dir:").strip())
    draft_payload = json.loads((run_dir / "issue-draft.json").read_text(encoding="utf-8"))

    assert status == 0
    assert (run_dir / "run-request.json").exists()
    assert (run_dir / "issue-intake.json").exists()
    assert (run_dir / "issue-draft.json").exists()
    assert (run_dir / "issue.md").exists()
    assert (run_dir / "run-record.json").exists()
    assert not (run_dir / "execution-result.json").exists()
    assert draft_payload["issue_ref"] == "cracklings3d/precision-squad#67"
    assert draft_payload["summary"] == "Add the create issue stage command"
    assert draft_payload["provenance"]["source_artifacts"] == ["run-request.json", "issue-intake.json"]


def test_review_issue_prints_approved_review_output(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    issue_review = IssueReview(
        run_id="run-123",
        issue_ref="cracklings3d/precision-squad#68",
        review_status="approved",
        summary="Planning may proceed because issue-draft.json passed the local planner-safety review.",
        feedback=(),
        provenance=IssueReviewProvenance(
            source_artifact="issue-draft.json",
            run_id="run-123",
            issue_ref="cracklings3d/precision-squad#68",
        ),
    )

    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.review_issue",
        lambda self, *, params: __import__(
            "precision_squad.coordinator", fromlist=["ReviewIssueReport"]
        ).ReviewIssueReport(
            run_record=RunRecord(
                run_id="run-123",
                issue_ref="cracklings3d/precision-squad#68",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-123"),
            ),
            issue_review=issue_review,
            exit_code=0,
        ),
    )

    status = main(["review", "issue", "run-123", "--runs-dir", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 0
    assert "Review Status: approved" in captured.out
    assert "Artifacts: issue-review.json" in captured.out


def test_review_issue_prints_feedback_for_changes_requested(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    issue_review = IssueReview(
        run_id="run-123",
        issue_ref="cracklings3d/precision-squad#68",
        review_status="changes_requested",
        summary="Planning must stop because issue-draft.json has 1 planner-safety finding that require changes.",
        feedback=(
            IssueReviewFeedback(
                code="missing_summary",
                message="issue-draft.json must include a non-empty summary before planning can proceed.",
                artifact="issue-draft.json",
                field="summary",
            ),
        ),
        provenance=IssueReviewProvenance(
            source_artifact="issue-draft.json",
            run_id="run-123",
            issue_ref="cracklings3d/precision-squad#68",
        ),
    )

    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.review_issue",
        lambda self, *, params: __import__(
            "precision_squad.coordinator", fromlist=["ReviewIssueReport"]
        ).ReviewIssueReport(
            run_record=RunRecord(
                run_id="run-123",
                issue_ref="cracklings3d/precision-squad#68",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-123"),
            ),
            issue_review=issue_review,
            exit_code=2,
        ),
    )

    status = main(["review", "issue", "run-123", "--runs-dir", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 2
    assert "Review Status: changes_requested" in captured.out
    assert "missing_summary" in captured.out


def test_review_issue_uses_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        "[review.issue]\nruns_dir = \".precision-squad/runs\"\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    captured_runs_dir: dict[str, str] = {}
    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.review_issue",
        lambda self, *, params: (
            captured_runs_dir.__setitem__("runs_dir", str(params.runs_dir)),
            __import__("precision_squad.coordinator", fromlist=["ReviewIssueReport"]).ReviewIssueReport(
                run_record=RunRecord(
                    run_id="run-123",
                    issue_ref="owner/repo#1",
                    status="runnable",
                    created_at="2026-05-01T00:00:00Z",
                    updated_at="2026-05-01T00:00:00Z",
                    run_dir=str(tmp_path / ".precision-squad" / "runs" / "run-123"),
                ),
                issue_review=IssueReview(
                    run_id="run-123",
                    issue_ref="owner/repo#1",
                    review_status="blocked",
                    summary="Planning must stop because review issue is blocked by 1 blocking finding in issue-draft.json.",
                    feedback=(
                        IssueReviewFeedback(
                            code="issue_draft_missing",
                            message="Create issue must persist issue-draft.json before review issue can run.",
                            artifact="issue-draft.json",
                            field="",
                        ),
                    ),
                    provenance=IssueReviewProvenance(
                        source_artifact="issue-draft.json",
                        run_id="run-123",
                        issue_ref="owner/repo#1",
                    ),
                ),
                exit_code=3,
            ),
        )[1],
    )

    status = main(["review", "issue", "run-123"])

    captured = capsys.readouterr()
    assert status == 3
    assert Path(captured_runs_dir["runs_dir"]) == (tmp_path / ".precision-squad" / "runs")
    assert "Review Status: blocked" in captured.out


def test_review_plan_prints_approved_review_output(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan_review = PlanReview(
        run_id="run-123",
        issue_ref="cracklings3d/precision-squad#70",
        review_status="approved",
        summary="Implementation may proceed because approved-plan.json passed the same-run plan review gate.",
        feedback=(),
        provenance=PlanReviewProvenance(
            source_artifact="approved-plan.json",
            run_id="run-123",
            issue_ref="cracklings3d/precision-squad#70",
        ),
    )

    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.review_plan",
        lambda self, *, params: __import__(
            "precision_squad.coordinator", fromlist=["ReviewPlanReport"]
        ).ReviewPlanReport(
            run_record=RunRecord(
                run_id="run-123",
                issue_ref="cracklings3d/precision-squad#70",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-123"),
            ),
            plan_review=plan_review,
            exit_code=0,
        ),
    )

    status = main(["review", "plan", "run-123", "--runs-dir", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 0
    assert "Review Status: approved" in captured.out
    assert "Artifacts: plan-review.json" in captured.out


def test_review_plan_prints_feedback_for_changes_requested(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan_review = PlanReview(
        run_id="run-123",
        issue_ref="cracklings3d/precision-squad#70",
        review_status="changes_requested",
        summary="Implementation must stop because approved-plan.json has 1 implementation-ingress finding that require changes.",
        feedback=(
            PlanReviewFeedback(
                code="missing_retrieval_surface_summary",
                message="approved-plan.json must include a non-empty retrieval_surface_summary so implement ingress does not have to guess the reviewed plan surface.",
                artifact="approved-plan.json",
                field="retrieval_surface_summary",
            ),
        ),
        provenance=PlanReviewProvenance(
            source_artifact="approved-plan.json",
            run_id="run-123",
            issue_ref="cracklings3d/precision-squad#70",
        ),
    )

    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.review_plan",
        lambda self, *, params: __import__(
            "precision_squad.coordinator", fromlist=["ReviewPlanReport"]
        ).ReviewPlanReport(
            run_record=RunRecord(
                run_id="run-123",
                issue_ref="cracklings3d/precision-squad#70",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-123"),
            ),
            plan_review=plan_review,
            exit_code=2,
        ),
    )

    status = main(["review", "plan", "run-123", "--runs-dir", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 2
    assert "Review Status: changes_requested" in captured.out
    assert "missing_retrieval_surface_summary" in captured.out


def test_review_plan_uses_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        "[review.plan]\nruns_dir = \".precision-squad/runs\"\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    captured_runs_dir: dict[str, str] = {}
    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.review_plan",
        lambda self, *, params: (
            captured_runs_dir.__setitem__("runs_dir", str(params.runs_dir)),
            __import__("precision_squad.coordinator", fromlist=["ReviewPlanReport"]).ReviewPlanReport(
                run_record=RunRecord(
                    run_id="run-123",
                    issue_ref="owner/repo#1",
                    status="runnable",
                    created_at="2026-05-01T00:00:00Z",
                    updated_at="2026-05-01T00:00:00Z",
                    run_dir=str(tmp_path / ".precision-squad" / "runs" / "run-123"),
                ),
                plan_review=PlanReview(
                    run_id="run-123",
                    issue_ref="owner/repo#1",
                    review_status="blocked",
                    summary="Implementation must stop because review plan is blocked by 1 prerequisite finding.",
                    feedback=(
                        PlanReviewFeedback(
                            code="approved_plan_missing",
                            message="plan must persist approved-plan.json for the same run before review plan can run.",
                            artifact="approved-plan.json",
                            field="",
                        ),
                    ),
                    provenance=PlanReviewProvenance(
                        source_artifact="approved-plan.json",
                        run_id="run-123",
                        issue_ref="owner/repo#1",
                    ),
                ),
                exit_code=3,
            ),
        )[1],
    )

    status = main(["review", "plan", "run-123"])

    captured = capsys.readouterr()
    assert status == 3
    assert Path(captured_runs_dir["runs_dir"]) == (tmp_path / ".precision-squad" / "runs")
    assert "Review Status: blocked" in captured.out


def test_review_impl_prints_approved_review_output(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    impl_review = ImplReviewResult(
        review_status="approved",
        summary="Published PR passed implementation review.",
        pull_request_url="https://github.com/cracklings3d/precision-squad/pull/72",
        pull_number=72,
        pull_head_sha="head-sha",
        reviewer_status="approved",
        reviewer_summary="Reviewer approved.",
        architect_status="approved",
        architect_summary="Architect approved.",
    )

    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.review_impl",
        lambda self, *, params, dependencies: __import__(
            "precision_squad.coordinator", fromlist=["ReviewImplReport"]
        ).ReviewImplReport(
            run_record=RunRecord(
                run_id="run-123",
                issue_ref="cracklings3d/precision-squad#72",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-123"),
            ),
            impl_review=impl_review,
            exit_code=0,
        ),
    )

    status = main(["review", "impl", "run-123", "--runs-dir", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 0
    assert "Review Status: approved" in captured.out
    assert "Artifacts: impl-review.json" in captured.out
    assert "Downstream Automation Allowed: True" in captured.out


def test_review_impl_prints_feedback_for_blocked_review(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    impl_review = ImplReviewResult(
        review_status="blocked",
        summary="Implementation review could not validate provenance.",
        pull_request_url="https://github.com/cracklings3d/precision-squad/pull/72",
        pull_number=72,
        pull_head_sha="head-sha",
        feedback=(
            ImplReviewFeedback(
                code="pr_body_run_id_mismatch",
                message="Published PR Run ID marker does not match run-record.json.",
                source="stage",
            ),
        ),
        reviewer_status="not_run",
        reviewer_summary="Reviewer did not run because review impl was blocked.",
        architect_status="not_run",
        architect_summary="Architect did not run because review impl was blocked.",
        issue_comment_url="comment-url",
        issue_reopened=True,
    )

    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.review_impl",
        lambda self, *, params, dependencies: __import__(
            "precision_squad.coordinator", fromlist=["ReviewImplReport"]
        ).ReviewImplReport(
            run_record=RunRecord(
                run_id="run-123",
                issue_ref="cracklings3d/precision-squad#72",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-123"),
            ),
            impl_review=impl_review,
            exit_code=3,
        ),
    )

    status = main(["review", "impl", "run-123", "--runs-dir", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 3
    assert "Review Status: blocked" in captured.out
    assert "pr_body_run_id_mismatch" in captured.out
    assert "Review Feedback URL: comment-url" in captured.out


def test_review_impl_uses_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        "[review.impl]\nruns_dir = \".precision-squad/runs\"\nreview_model = \"test-model\"\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    captured_params: dict[str, str] = {}
    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.review_impl",
        lambda self, *, params, dependencies: (
            captured_params.__setitem__("runs_dir", str(params.runs_dir)),
            captured_params.__setitem__("review_model", str(params.review_model)),
            __import__("precision_squad.coordinator", fromlist=["ReviewImplReport"]).ReviewImplReport(
                run_record=RunRecord(
                    run_id="run-123",
                    issue_ref="owner/repo#1",
                    status="runnable",
                    created_at="2026-05-01T00:00:00Z",
                    updated_at="2026-05-01T00:00:00Z",
                    run_dir=str(tmp_path / ".precision-squad" / "runs" / "run-123"),
                ),
                impl_review=ImplReviewResult(
                    review_status="approved",
                    summary="ok",
                    pull_request_url="https://github.com/owner/repo/pull/1",
                    pull_number=1,
                    pull_head_sha="sha",
                ),
                exit_code=0,
            ),
        )[2],
    )

    status = main(["review", "impl", "run-123"])

    captured = capsys.readouterr()
    assert status == 0
    assert Path(captured_params["runs_dir"]) == (tmp_path / ".precision-squad" / "runs")
    assert captured_params["review_model"] == "test-model"
    assert "Review Status: approved" in captured.out


def test_review_issue_end_to_end_persists_approved_issue_review(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    request = RunRequest(
        issue_ref="cracklings3d/precision-squad#68",
        runs_dir=str(runs_dir),
    )
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "precision-squad", 68),
            title="Add the review issue stage gate",
            body="Persist an issue review artifact.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/precision-squad/issues/68",
        ),
        summary="Add the review issue stage gate",
        problem_statement="Persist an issue review artifact.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    record = store.create_run(request, intake)

    status = main(["review", "issue", record.run_id, "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    payload = json.loads((Path(record.run_dir) / "issue-review.json").read_text(encoding="utf-8"))
    assert status == 0
    assert payload["review_status"] == "approved"
    assert payload["provenance"]["source_artifact"] == "issue-draft.json"
    assert "Review Status: approved" in captured.out


def test_review_issue_end_to_end_persists_changes_requested_when_summary_missing(
    capsys, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/precision-squad#68",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "issue-draft.json").write_text(
        json.dumps(
            {
                "owner": "cracklings3d",
                "repo": "precision-squad",
                "number": 68,
                "issue_ref": "cracklings3d/precision-squad#68",
                "issue_url": "https://github.com/cracklings3d/precision-squad/issues/68",
                "title": "Add the review issue stage gate",
                "summary": "",
                "problem_statement": "Persist an issue review artifact.",
                "labels": ["enhancement"],
                "intake_status": "runnable",
                "intake_reason_codes": [],
                "provenance": {
                    "source_artifacts": ["run-request.json", "issue-intake.json"],
                    "requested_issue_ref": "cracklings3d/precision-squad#68",
                },
            }
        ),
        encoding="utf-8",
    )

    status = main(["review", "issue", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    payload = json.loads((run_dir / "issue-review.json").read_text(encoding="utf-8"))
    assert status == 2
    assert payload["review_status"] == "changes_requested"
    assert payload["feedback"][0]["code"] == "missing_summary"
    assert "Review Status: changes_requested" in captured.out


def test_review_issue_end_to_end_persists_blocked_when_issue_draft_missing(
    capsys, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/precision-squad#68",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )

    status = main(["review", "issue", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    payload = json.loads((run_dir / "issue-review.json").read_text(encoding="utf-8"))
    assert status == 3
    assert payload["review_status"] == "blocked"
    assert payload["feedback"][0]["code"] == "issue_draft_missing"
    assert "Review Status: blocked" in captured.out


def test_plan_run_prints_persisted_artifact_output(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "owner/repo#1",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")

    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.persist_approved_plan_for_planning",
        lambda self, *, params: run_dir / "approved-plan.json",
    )

    status = main(
        [
            "plan",
            "run-123",
            "--runs-dir",
            str(runs_dir),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Run ID: run-123" in captured.out
    assert "Issue: owner/repo#1" in captured.out
    assert "Artifacts: approved-plan.json" in captured.out


def test_plan_run_persists_approved_plan_for_reviewed_run(capsys, tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "owner/repo#1",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "issue-review.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "owner/repo#1",
                "review_status": "approved",
                "summary": "Planning may proceed because issue-draft.json passed the local planner-safety review.",
                "feedback": [],
                "provenance": {
                    "source_artifact": "issue-draft.json",
                    "run_id": "run-123",
                    "issue_ref": "owner/repo#1",
                },
            }
        ),
        encoding="utf-8",
    )
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")

    status = main(
        [
            "plan",
            "run-123",
            "--runs-dir",
            str(runs_dir),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads((run_dir / "approved-plan.json").read_text(encoding="utf-8"))
    assert status == 0
    assert payload["issue_ref"] == "owner/repo#1"
    assert payload["approved"] is True
    assert "Approved Plan:" in captured.out


def test_plan_run_rejects_missing_issue_review_artifact(capsys, tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "owner/repo#1",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")

    status = main(
        [
            "plan",
            "run-123",
            "--runs-dir",
            str(runs_dir),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "requires issue-review.json" in captured.err
    assert not (run_dir / "approved-plan.json").exists()


@pytest.mark.parametrize("review_status", ["changes_requested", "blocked"])
def test_plan_run_rejects_non_approved_issue_review(
    capsys, tmp_path: Path, review_status: str
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "owner/repo#1",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "issue-review.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "owner/repo#1",
                "review_status": review_status,
                "summary": "Planning must stop.",
                "feedback": [],
                "provenance": {
                    "source_artifact": "issue-draft.json",
                    "run_id": "run-123",
                    "issue_ref": "owner/repo#1",
                },
            }
        ),
        encoding="utf-8",
    )
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")

    status = main(
        [
            "plan",
            "run-123",
            "--runs-dir",
            str(runs_dir),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "review_status" in captured.err
    assert review_status in captured.err
    assert not (run_dir / "approved-plan.json").exists()


def test_repair_agent_choices_include_legacy_compatibility_input() -> None:
    assert _REPAIR_AGENT_CHOICES == ("opencode", "none", "vercel-ai")


def test_build_repair_adapter_returns_none_for_none_agent() -> None:
    assert _build_repair_adapter(repair_agent="none", repair_model=None) is None


def test_build_repair_adapter_returns_opencode_as_primary_concrete_implementation() -> None:
    adapter = _build_repair_adapter(repair_agent="opencode", repair_model="test-model")

    assert isinstance(adapter, RepairAdapter)
    assert isinstance(adapter, OpenCodeRepairAdapter)
    assert adapter.model == "test-model"


def test_build_repair_adapter_returns_compatibility_vercel_ai_implementation() -> None:
    adapter = _build_repair_adapter(repair_agent="vercel-ai", repair_model="test-model")

    assert isinstance(adapter, RepairAdapter)
    assert isinstance(adapter, VercelAIRepairAdapter)
    assert adapter.model == "test-model"


def test_cli_omitted_repair_agent_defaults_to_opencode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Example issue",
            body="Example body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Example summary",
        problem_statement="Example problem",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    captured_params: dict[str, object] = {}

    def fake_repair_issue(self, *, params, intake, dependencies):
        del self, dependencies
        captured_params["repair_agent"] = params.repair_agent
        return RepairIssueReport(
            intake=intake,
            run_record=RunRecord(
                run_id="run-1",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-1"),
            ),
            execution_result=ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="Stub execution completed.",
                detail_codes=(),
            ),
            evaluation_result=EvaluationResult(
                status="success",
                summary="Stub evaluation completed.",
                detail_codes=(),
            ),
            governance_verdict=GovernanceVerdict(
                status="approved",
                summary="Approved",
                reason_codes=(),
            ),
            publish_plan=PublishPlan(
                status="draft_pr",
                title="title",
                body="body",
                reason_codes=(),
            ),
            publish_result=PublishResult(
                status="dry_run",
                target="draft_pr",
                summary="dry run",
                url=None,
            ),
            repair_result=None,
            qa_result=None,
            post_publish_review_result=None,
            exit_code=0,
        )

    monkeypatch.setattr("precision_squad.cli.RunCoordinator.repair_issue", fake_repair_issue)

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    assert status == 0
    assert captured_params["repair_agent"] == "opencode"


def test_cli_repair_dependencies_construct_seam_compatible_adapter() -> None:
    adapter = _CliRepairDependencies().create_repair_adapter(
        repair_agent="opencode",
        repair_model=None,
    )

    assert isinstance(adapter, RepairAdapter)
    assert isinstance(adapter, OpenCodeRepairAdapter)


def test_version_flag_shows_package_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert __version__ in captured.out


def test_repair_issue_help_shows_current_choices_and_legacy_note(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["repair", "issue", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "--repair-agent {opencode,none}" in captured.out
    assert "Defaults to opencode" in captured.out
    assert "when omitted. Normal choices: opencode, none." in captured.out
    assert "Legacy" in captured.out
    assert "compatibility input: vercel-ai" in captured.out
    assert "{opencode,none,vercel-ai}" not in captured.out


def test_readme_documents_repair_agent_contract() -> None:
    readme_text = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    assert "default when omitted: `opencode`" in readme_text
    assert "normal supported choices: `opencode`, `none`" in readme_text
    assert "`vercel-ai` is accepted only as a retired compatibility input" in readme_text
    assert "not an active supported repair mode" in readme_text


def test_install_skill_writes_skill_md(capsys, tmp_path: Path) -> None:
    status = main(["install-skill", "--project-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert (tmp_path / "SKILL.md").exists()
    assert "Installed skill:" in captured.out


def test_install_skill_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("existing\n", encoding="utf-8")

    status = main(["install-skill", "--project-root", str(tmp_path)])

    assert status == 1
    assert skill_path.read_text(encoding="utf-8") == "existing\n"


def test_install_skill_no_force_overrides_true_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    skill_path = project_root / "SKILL.md"
    skill_path.write_text("existing\n", encoding="utf-8")
    (tmp_path / ".precision-squad.toml").write_text(
        (
            "[install-skill]\n"
            f'project_root = "{project_root.as_posix()}"\n'
            "force = true\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    status = main(["install-skill", "--no-force"])

    assert status == 1
    assert skill_path.read_text(encoding="utf-8") == "existing\n"


def test_bootstrap_skill_cancels_without_confirmation(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    status = bootstrap_main(["--project-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert "Bootstrap cancelled" in captured.out
    assert not (tmp_path / "SKILL.md").exists()


def test_bootstrap_skill_installs_after_confirmation(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")

    status = bootstrap_main(["--project-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert "This bootstrap will install the precision-squad project skill." in captured.out
    assert (tmp_path / "SKILL.md").exists()


def test_run_issue_placeholder_returns_nonzero(
    capsys, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OpenCode_Github_Token", raising=False)

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "approved-plan-path" in captured.err.lower()


def test_run_issue_prints_runnable_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Add version flag.",
                "implementation_steps": ["Update CLI"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Stub execution completed.",
            detail_codes=(),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Classification: runnable" in captured.out
    assert "Run ID:" in captured.out
    assert "Summary: Add --version flag to CLI" in captured.out
    assert "Execution Status: completed" in captured.out


def test_repair_issue_alias_prints_runnable_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Add version flag.",
                "implementation_steps": ["Update CLI"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Stub execution completed.",
            detail_codes=(),
        ),
    )

    status = main(
        [
            "repair",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Classification: runnable" in captured.out
    assert "Execution Status: completed" in captured.out


@pytest.mark.parametrize("command_name", ["repair", "run"])
def test_repair_issue_and_run_issue_print_same_stage_stop_output(
    command_name: str,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Example issue",
            body="Example body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Example summary",
        problem_statement="Example problem",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")
    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.repair_issue",
        lambda self, *, params, intake, dependencies: RepairIssueReport(
            intake=intake,
            run_record=RunRecord(
                run_id="run-1",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-1"),
            ),
            issue_review=IssueReview(
                run_id="run-1",
                issue_ref="owner/repo#1",
                review_status="approved",
                summary="Issue review approved.",
                feedback=(),
                provenance=IssueReviewProvenance(
                    source_artifact="issue-draft.json",
                    run_id="run-1",
                    issue_ref="owner/repo#1",
                ),
            ),
            plan_review=PlanReview(
                run_id="run-1",
                issue_ref="owner/repo#1",
                review_status="changes_requested",
                summary="Plan review needs changes.",
                feedback=(
                    PlanReviewFeedback(
                        code="missing_retrieval_surface_summary",
                        message="Need retrieval surface summary.",
                        artifact="approved-plan.json",
                        field="retrieval_surface_summary",
                    ),
                ),
                provenance=PlanReviewProvenance(
                    source_artifact="approved-plan.json",
                    run_id="run-1",
                    issue_ref="owner/repo#1",
                ),
            ),
            exit_code=2,
        ),
    )

    status = main(
        [
            command_name,
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "Issue Review: approved" in captured.out
    assert "Plan Review: changes_requested" in captured.out
    assert "Execution Status:" not in captured.out


def test_run_issue_prints_blocked_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 1),
            title="[Plan] Markdown to PDF Renderer",
            body="## Project Plan",
            labels=("plan",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/1",
        ),
        summary="Markdown to PDF Renderer",
        problem_statement="Project plan",
        assessment=IssueAssessment(
            status="blocked",
            reason_codes=("issue_marked_as_plan",),
        ),
    )

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#1",
                "plan_summary": "Plan artifact.",
                "implementation_steps": ["Do thing"],
                "named_references": [],
                "retrieval_surface_summary": "",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "Classification: blocked" in captured.out
    assert "issue_marked_as_plan" in captured.out
    assert "Issue Review: changes_requested" in captured.out


def test_run_issue_persists_run_artifacts(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Add version flag.",
                "implementation_steps": ["Update CLI"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Stub execution completed.",
            detail_codes=(),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    run_dir_line = next(line for line in captured.out.splitlines() if line.startswith("Run Dir:"))
    run_dir = Path(run_dir_line.removeprefix("Run Dir:").strip())

    assert status == 0
    assert (run_dir / "run-request.json").exists()
    assert (run_dir / "issue-intake.json").exists()
    assert (run_dir / "run-record.json").exists()
    assert (run_dir / "execution-result.json").exists()
    assert (run_dir / "evaluation-result.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert (run_dir / "publish-plan.json").exists()
    assert (run_dir / "publish-result.json").exists()


def test_run_issue_uses_executor_and_persists_execution_result(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Add version flag.",
                "implementation_steps": ["Update CLI"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="blocked",
            executor_name="docs",
            summary="Executor wiring is not implemented yet.",
            detail_codes=("executor_not_implemented",),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    run_dir_line = next(line for line in captured.out.splitlines() if line.startswith("Run Dir:"))
    run_dir = Path(run_dir_line.removeprefix("Run Dir:").strip())

    assert status == 4
    assert (run_dir / "execution-result.json").exists()
    assert (run_dir / "evaluation-result.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert not (run_dir / "publish-plan.json").exists()
    assert not (run_dir / "publish-result.json").exists()
    assert "Execution Status: blocked" in captured.out


def test_run_issue_does_not_enter_repair_loop_when_docs_are_missing(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = _write_valid_plan(tmp_path, issue_ref="cracklings3d/markdown-pdf-renderer#9")
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="missing_docs",
            executor_name="docs",
            summary="Missing documented QA command.",
            detail_codes=("docs_qa_command_missing",),
            artifact_dir=str(run_dir / "execution-contract"),
        ),
    )

    def fail_if_repair_runs(**kwargs):
        raise AssertionError("repair loop should not run when docs are missing")

    monkeypatch.setattr("precision_squad.cli.run_repair_qa_loop", fail_if_repair_runs)

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 4
    assert "Execution Status: missing_docs" in captured.out
    assert "Governance: blocked" in captured.out
    assert "Publish Plan:" not in captured.out


def test_docs_remediation_issue_runs_repair_without_recursive_follow_up_issue(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body=(
                "<!-- precision-squad:docs-remediation -->\n"
                "<!-- precision-squad:target-findings:[{\"rule_id\":\"docs_setup_prerequisites_ambiguous\",\"section_key\":\"docs\",\"source_path\":\"repository-docs\",\"subject_key\":\"docs-blocker\"}] -->\n\n"
                "## Context\nFix docs."
            ),
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = _write_valid_plan(tmp_path, issue_ref="cracklings3d/markdown-pdf-renderer#16")

    workspace_root = tmp_path / "workspace"
    (workspace_root / "repo").mkdir(parents=True)

    def fake_execute(self, intake, record, run_dir):
        repo_path = self.repo_path
        del intake, record
        artifact_dir = run_dir / "execution-contract"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "contract.json").write_text("{}\n", encoding="utf-8")
        (artifact_dir / "docs-fix-prompt.txt").write_text("Fix docs.\n", encoding="utf-8")
        (artifact_dir / "README.snapshot.md").write_text("# README\n", encoding="utf-8")
        if repo_path == workspace_root / "repo":
            return ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="Repository documentation yielded an explicit local setup and QA contract.",
                detail_codes=("docs_contract_ready",),
                artifact_dir=str(artifact_dir),
            )
        return ExecutionResult(
            status="missing_docs",
            executor_name="docs",
            summary="Missing documented QA command.",
            detail_codes=("docs_qa_command_missing",),
            artifact_dir=str(artifact_dir),
        )

    monkeypatch.setattr("precision_squad.cli.DocsFirstExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "precision_squad.cli.run_docs_remediation_repair",
        lambda **kwargs: __import__("precision_squad.models", fromlist=["RepairResult"]).RepairResult(
            status="completed",
            summary="Repair stage completed and produced source changes.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(workspace_root),
            patch_path=str(tmp_path / "repair.patch"),
        ),
    )

    def fail_if_standard_repair_runs(**kwargs):
        raise AssertionError("standard repair/QA loop should not run for docs-remediation issues")

    monkeypatch.setattr("precision_squad.cli.run_repair_qa_loop", fail_if_standard_repair_runs)

    status = main(
        [
            "repair",
            "issue",
            "cracklings3d/markdown-pdf-renderer#16",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Execution Status: completed" in captured.out
    assert "Repair Status: completed" in captured.out
    assert "Publish Plan: draft_pr" in captured.out


def test_docs_remediation_issue_stays_blocked_when_revalidation_fails(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body="<!-- precision-squad:docs-remediation -->\n\n## Context\nFix docs.",
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = _write_valid_plan(tmp_path, issue_ref="cracklings3d/markdown-pdf-renderer#16")

    workspace_root = tmp_path / "workspace"
    (workspace_root / "repo").mkdir(parents=True)

    def fake_execute(self, intake, record, run_dir):
        del self, intake, record
        artifact_dir = run_dir / "execution-contract"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "contract.json").write_text(
            json.dumps(
                {
                    "findings": [
                        {
                            "rule_id": "docs_setup_prerequisites_ambiguous",
                            "source_path": "repository-docs",
                            "section_key": "docs",
                            "subject_key": "docs-blocker",
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (artifact_dir / "docs-fix-prompt.txt").write_text("Fix docs.\n", encoding="utf-8")
        (artifact_dir / "README.snapshot.md").write_text("# README\n", encoding="utf-8")
        return ExecutionResult(
            status="missing_docs",
            executor_name="docs",
            summary="Still missing deterministic setup guidance.",
            detail_codes=("docs_setup_prerequisites_ambiguous",),
            artifact_dir=str(artifact_dir),
        )

    monkeypatch.setattr("precision_squad.cli.DocsFirstExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "precision_squad.cli.run_docs_remediation_repair",
        lambda **kwargs: __import__("precision_squad.models", fromlist=["RepairResult"]).RepairResult(
            status="completed",
            summary="Repair stage completed and produced source changes.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(workspace_root),
            patch_path=str(tmp_path / "repair.patch"),
        ),
    )
    monkeypatch.setattr(
        "precision_squad.cli.run_repair_qa_loop",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("standard repair/QA loop should not run for docs-remediation issues")
        ),
    )

    status = main(
        [
            "repair",
            "issue",
            "cracklings3d/markdown-pdf-renderer#16",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 4
    assert "Execution Status: missing_docs" in captured.out
    assert "Governance: blocked" in captured.out
    assert "Publish Plan:" not in captured.out


def test_run_issue_persists_repair_result_when_synthesis_artifacts_exist(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = _write_valid_plan(tmp_path, issue_ref="cracklings3d/markdown-pdf-renderer#9")

    def fake_execute(self, intake, record, run_dir):
        del self, intake
        artifact_dir = run_dir / "execution-contract"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "contract.json").write_text("{}\n", encoding="utf-8")
        return ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Documented execution contract ready.",
            detail_codes=("docs_contract_ready",),
            artifact_dir=str(artifact_dir),
        )

    monkeypatch.setattr("precision_squad.cli.DocsFirstExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "precision_squad.cli.run_repair_qa_loop",
        lambda **kwargs: (
            __import__("precision_squad.models", fromlist=["RepairResult"]).RepairResult(
                status="not_configured",
                summary=(
                    "A documented local execution contract was prepared, but no repair agent was configured."
                ),
                detail_codes=("repair_stage_not_configured",),
            ),
            __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
                status="failed",
                summary="Baseline QA failed.",
                detail_codes=("qa_failed",),
                phase="baseline",
            ),
            __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
                status="not_run",
                summary="QA did not run.",
                detail_codes=("qa_not_run",),
                phase="final",
            ),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--repair-agent",
            "none",
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    run_dir_line = next(line for line in captured.out.splitlines() if line.startswith("Run Dir:"))
    run_dir = Path(run_dir_line.removeprefix("Run Dir:").strip())

    assert status == 4
    assert (run_dir / "repair-result.json").exists()
    assert (run_dir / "qa-baseline-result.json").exists()
    assert (run_dir / "qa-result.json").exists()
    assert "Repair Status: not_configured" in captured.out
    assert "QA Status: not_run" in captured.out
    assert "Publish Plan:" not in captured.out


def test_run_issue_marks_baseline_tolerant_success_approved(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    plan_path = _write_valid_plan(tmp_path, issue_ref="cracklings3d/markdown-pdf-renderer#9")

    def fake_execute(self, intake, record, run_dir):
        del self, intake
        artifact_dir = run_dir / "execution-contract"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "contract.json").write_text("{}\n", encoding="utf-8")
        return ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Documented execution contract ready.",
            detail_codes=("docs_contract_ready",),
            artifact_dir=str(artifact_dir),
        )

    monkeypatch.setattr("precision_squad.cli.DocsFirstExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "precision_squad.cli.run_repair_qa_loop",
        lambda **kwargs: (
            __import__("precision_squad.models", fromlist=["RepairResult"]).RepairResult(
                status="completed",
                summary="Repair completed.",
                detail_codes=("repair_stage_completed",),
                workspace_path=str(tmp_path / "workspace"),
                patch_path=str(tmp_path / "repair.patch"),
            ),
            __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
                status="failed",
                summary="Baseline QA failed.",
                detail_codes=("qa_failed",),
                phase="baseline",
            ),
            __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
                status="failed",
                summary="Repair QA improved on baseline.",
                detail_codes=("qa_failed",),
                phase="final",
                quality="improved",
            ),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Governance: approved" in captured.out
    assert "Publish Plan: draft_pr" in captured.out


def test_publish_run_reuses_existing_artifacts(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {
                        "owner": "cracklings3d",
                        "repo": "markdown-pdf-renderer",
                        "number": 9,
                    },
                    "title": "[Enhancement] Add --version flag to CLI",
                    "body": "## Description\nAdd a version flag.",
                    "labels": ["enhancement"],
                    "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
                    "comments": ["Prior rejection feedback"],
                },
                "summary": "Add --version flag to CLI",
                "problem_statement": "Add a version flag.",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-plan.json").write_text(
        json.dumps(
            {
                "status": "draft_pr",
                "title": "Add --version flag to CLI",
                "body": "body",
                "reason_codes": [],
                "pull_request_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/15",
                "pull_number": 15,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "status": "runnable",
                "created_at": "2026-04-27T00:00:00Z",
                "updated_at": "2026-04-27T00:00:00Z",
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-result.json").write_text(
        json.dumps(
            {
                "status": "dry_run",
                "target": "draft_pr",
                "summary": "dry run",
                "url": None,
                "branch_name": "precision-squad/run-20260428-012411-5e87af7f",
                "pull_number": 15,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "precision_squad.cli.execute_publish_plan",
        lambda intake, plan, publish, run_dir: __import__(
            "precision_squad.models", fromlist=["PublishResult"]
        ).PublishResult(
            status="published",
            target=plan.status,
            summary="Published existing run.",
            url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/15",
            branch_name="precision-squad/run-20260428-012411-5e87af7f",
            pull_number=15,
        ),
    )
    monkeypatch.setattr(
        "precision_squad.cli._run_post_publish_review_if_needed",
        lambda **kwargs: None,
    )

    status = main(["publish", "run", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    assert status == 0
    assert "Publish Result: published" in captured.out
    assert (
        "Publish URL: https://github.com/cracklings3d/markdown-pdf-renderer/pull/15"
        in captured.out
    )


def test_publish_run_resumes_post_publish_review_for_published_result(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {
                        "owner": "cracklings3d",
                        "repo": "markdown-pdf-renderer",
                        "number": 9,
                    },
                    "title": "[Enhancement] Add --version flag to CLI",
                    "body": "## Description\nAdd a version flag.",
                    "labels": ["enhancement"],
                    "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
                },
                "summary": "Add --version flag to CLI",
                "problem_statement": "Add a version flag.",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-plan.json").write_text(
        json.dumps(
            {
                "status": "draft_pr",
                "title": "Add --version flag to CLI",
                "body": "body",
                "reason_codes": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "status": "runnable",
                "created_at": "2026-04-27T00:00:00Z",
                "updated_at": "2026-04-27T00:00:00Z",
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-result.json").write_text(
        json.dumps(
            {
                "status": "published",
                "target": "draft_pr",
                "summary": "Published existing run.",
                "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            }
        ),
        encoding="utf-8",
    )

    review_calls: list[str] = []

    def fail_if_republish(*args, **kwargs):
        raise AssertionError("publish should not rerun for an already published result")

    def fake_review(**kwargs):
        review_calls.append(kwargs["publish_result"].url or "")
        return PostPublishReviewResult(
            status="approved",
            summary="Reviewer and architect approved the published pull request.",
            pull_request_url=kwargs["publish_result"].url,
            pull_number=13,
            reviewer_status="approved",
            reviewer_summary="Reviewer approved.",
            architect_status="approved",
            architect_summary="Architect approved.",
        )

    monkeypatch.setattr("precision_squad.cli.execute_publish_plan", fail_if_republish)
    monkeypatch.setattr("precision_squad.cli._run_post_publish_review_if_needed", fake_review)

    status = main(["publish", "run", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    review_payload = json.loads(
        (run_dir / "post-publish-review-result.json").read_text(encoding="utf-8")
    )

    assert status == 0
    assert review_calls == ["https://github.com/cracklings3d/markdown-pdf-renderer/pull/13"]
    assert "Publish Result: published" in captured.out
    assert "Publish URL: https://github.com/cracklings3d/markdown-pdf-renderer/pull/13" in captured.out
    assert "Post-Publish Review: approved" in captured.out
    assert review_payload["status"] == "approved"
    assert review_payload["pull_number"] == 13


def test_publish_run_retries_failed_post_publish_review(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {
                        "owner": "cracklings3d",
                        "repo": "markdown-pdf-renderer",
                        "number": 9,
                    },
                    "title": "[Enhancement] Add --version flag to CLI",
                    "body": "## Description\nAdd a version flag.",
                    "labels": ["enhancement"],
                    "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
                },
                "summary": "Add --version flag to CLI",
                "problem_statement": "Add a version flag.",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-plan.json").write_text(
        json.dumps(
            {
                "status": "draft_pr",
                "title": "Add --version flag to CLI",
                "body": "body",
                "reason_codes": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "status": "runnable",
                "created_at": "2026-04-27T00:00:00Z",
                "updated_at": "2026-04-27T00:00:00Z",
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-result.json").write_text(
        json.dumps(
            {
                "status": "published",
                "target": "draft_pr",
                "summary": "Published existing run.",
                "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "post-publish-review-result.json").write_text(
        json.dumps(
            {
                "status": "failed_infra",
                "summary": "Post-publish review could not complete successfully.",
                "pull_request_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "pull_number": 13,
                "reviewer_status": "failed_infra",
                "reviewer_summary": "Reviewer review agent could not produce a structured verdict.",
                "reviewer_feedback": [],
                "architect_status": "failed_infra",
                "architect_summary": "Architect review agent could not produce a structured verdict.",
                "architect_feedback": [],
                "issue_comment_url": None,
                "issue_reopened": False,
            }
        ),
        encoding="utf-8",
    )

    review_calls: list[str] = []

    def fail_if_republish(*args, **kwargs):
        raise AssertionError("publish should not rerun for an already published result")

    def fake_review(**kwargs):
        review_calls.append(kwargs["publish_result"].url or "")
        return PostPublishReviewResult(
            status="approved",
            summary="Reviewer and architect approved the published pull request.",
            pull_request_url=kwargs["publish_result"].url,
            pull_number=13,
            reviewer_status="approved",
            reviewer_summary="Reviewer approved.",
            architect_status="approved",
            architect_summary="Architect approved.",
        )

    monkeypatch.setattr("precision_squad.cli.execute_publish_plan", fail_if_republish)
    monkeypatch.setattr("precision_squad.cli._run_post_publish_review_if_needed", fake_review)

    status = main(["publish", "run", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    review_payload = json.loads(
        (run_dir / "post-publish-review-result.json").read_text(encoding="utf-8")
    )

    assert status == 0
    assert review_calls == ["https://github.com/cracklings3d/markdown-pdf-renderer/pull/13"]
    assert "Post-Publish Review: approved" in captured.out
    assert review_payload["status"] == "approved"


def test_publish_run_retries_stale_rejected_post_publish_review(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {
                        "owner": "cracklings3d",
                        "repo": "markdown-pdf-renderer",
                        "number": 9,
                    },
                    "title": "[Enhancement] Add --version flag to CLI",
                    "body": "## Description\nAdd a version flag.",
                    "labels": ["enhancement"],
                    "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
                },
                "summary": "Add --version flag to CLI",
                "problem_statement": "Add a version flag.",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-plan.json").write_text(
        json.dumps(
            {
                "status": "draft_pr",
                "title": "Add --version flag to CLI",
                "body": "body",
                "reason_codes": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "status": "runnable",
                "created_at": "2026-04-27T00:00:00Z",
                "updated_at": "2026-04-27T00:00:00Z",
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-result.json").write_text(
        json.dumps(
            {
                "status": "published",
                "target": "draft_pr",
                "summary": "Published existing run.",
                "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "post-publish-review-result.json").write_text(
        json.dumps(
            {
                "status": "rejected",
                "summary": "Post-publish review rejected the pull request and reopened the issue.",
                "pull_request_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "pull_number": 13,
                "pull_head_sha": "old-sha",
                "reviewer_status": "rejected",
                "reviewer_summary": "Reviewer rejected.",
                "reviewer_feedback": ["old feedback"],
                "architect_status": "approved",
                "architect_summary": "Architect approved.",
                "architect_feedback": [],
                "issue_comment_url": "https://github.com/example/comment",
                "issue_reopened": True,
            }
        ),
        encoding="utf-8",
    )

    review_calls: list[str] = []

    def fail_if_republish(*args, **kwargs):
        raise AssertionError("publish should not rerun for an already published result")

    def fake_review(**kwargs):
        review_calls.append(kwargs["publish_result"].url or "")
        return PostPublishReviewResult(
            status="approved",
            summary="Reviewer and architect approved the published pull request.",
            pull_request_url=kwargs["publish_result"].url,
            pull_number=13,
            pull_head_sha="new-sha",
            reviewer_status="approved",
            reviewer_summary="Reviewer approved.",
            architect_status="approved",
            architect_summary="Architect approved.",
        )

    monkeypatch.setattr("precision_squad.cli.execute_publish_plan", fail_if_republish)
    monkeypatch.setattr("precision_squad.cli._run_post_publish_review_if_needed", fake_review)
    monkeypatch.setattr("precision_squad.cli._post_publish_review_is_stale", lambda intake, review_result: True)

    status = main(["publish", "run", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    review_payload = json.loads(
        (run_dir / "post-publish-review-result.json").read_text(encoding="utf-8")
    )

    assert status == 0
    assert review_calls == ["https://github.com/cracklings3d/markdown-pdf-renderer/pull/13"]
    assert "Post-Publish Review: approved" in captured.out
    assert review_payload["status"] == "approved"
    assert review_payload["pull_head_sha"] == "new-sha"


def test_config_file_fills_default_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config file values are used when CLI args are not provided."""
    repo_path = tmp_path / "repo-from-config"
    runs_dir = tmp_path / "runs-from-config"
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")
    config_file = tmp_path / ".precision-squad.toml"
    config_file.write_text(
        (
            "[repair.issue]\n"
            f'repo_path = "{repo_path.as_posix()}"\n'
            f'runs_dir = "{runs_dir.as_posix()}"\n'
            'repair_agent = "none"\n'
            f'approved_plan_path = "{plan_path.as_posix()}"\n'
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Example issue",
            body="Example body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Example summary",
        problem_statement="Example problem",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    captured_params: dict[str, object] = {}

    def fake_repair_issue(self, *, params, intake, dependencies):
        del self, dependencies
        captured_params["repo_path"] = params.repo_path
        captured_params["runs_dir"] = params.runs_dir
        captured_params["repair_agent"] = params.repair_agent
        return RepairIssueReport(
            intake=intake,
            run_record=RunRecord(
                run_id="run-1",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs-from-config" / "run-1"),
            ),
            execution_result=ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="Stub execution completed.",
                detail_codes=(),
            ),
            evaluation_result=EvaluationResult(
                status="success",
                summary="Stub evaluation completed.",
                detail_codes=(),
            ),
            governance_verdict=GovernanceVerdict(
                status="approved",
                summary="Approved",
                reason_codes=(),
            ),
            publish_plan=PublishPlan(
                status="draft_pr",
                title="title",
                body="body",
                reason_codes=(),
            ),
            publish_result=PublishResult(
                status="dry_run",
                target="draft_pr",
                summary="dry run",
                url=None,
            ),
            repair_result=None,
            qa_result=None,
            post_publish_review_result=None,
            exit_code=0,
        )

    monkeypatch.setattr("precision_squad.cli.RunCoordinator.repair_issue", fake_repair_issue)

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    assert status == 0
    assert captured_params["repo_path"] == repo_path
    assert captured_params["runs_dir"] == runs_dir
    assert captured_params["repair_agent"] == "none"


def test_cli_args_override_config_file_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")
    config_file = tmp_path / ".precision-squad.toml"
    config_file.write_text(
        (
            "[repair.issue]\n"
            'repo_path = "/from/config"\n'
            'runs_dir = "/config/runs"\n'
            'repair_agent = "none"\n'
            f'approved_plan_path = "{plan_path.as_posix()}"\n'
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Example issue",
            body="Example body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Example summary",
        problem_statement="Example problem",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    captured_params: dict[str, object] = {}

    def fake_repair_issue(self, *, params, intake, dependencies):
        del self, dependencies
        captured_params["repo_path"] = params.repo_path
        captured_params["runs_dir"] = params.runs_dir
        captured_params["repair_agent"] = params.repair_agent
        return RepairIssueReport(
            intake=intake,
            run_record=RunRecord(
                run_id="run-1",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-1"),
            ),
            execution_result=ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="Stub execution completed.",
                detail_codes=(),
            ),
            evaluation_result=EvaluationResult(
                status="success",
                summary="Stub evaluation completed.",
                detail_codes=(),
            ),
            governance_verdict=GovernanceVerdict(
                status="approved",
                summary="Approved",
                reason_codes=(),
            ),
            publish_plan=PublishPlan(
                status="draft_pr",
                title="title",
                body="body",
                reason_codes=(),
            ),
            publish_result=PublishResult(
                status="dry_run",
                target="draft_pr",
                summary="dry run",
                url=None,
            ),
            repair_result=None,
            qa_result=None,
            post_publish_review_result=None,
            exit_code=0,
        )

    monkeypatch.setattr("precision_squad.cli.RunCoordinator.repair_issue", fake_repair_issue)

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo-from-cli"),
            "--runs-dir",
            str(tmp_path / "runs-from-cli"),
            "--repair-agent",
            "opencode",
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    assert status == 0
    assert captured_params["repo_path"] == tmp_path / "repo-from-cli"
    assert captured_params["runs_dir"] == tmp_path / "runs-from-cli"
    assert captured_params["repair_agent"] == "opencode"


def test_invalid_config_file_format_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    (tmp_path / ".precision-squad.toml").write_text("this is not valid toml [[[", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    status = main(["repair", "issue", "owner/repo#1"])

    captured = capsys.readouterr()
    assert status == 1
    assert "Invalid config file format" in captured.err


def test_empty_parent_namespace_config_returns_schema_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    (tmp_path / ".precision-squad.toml").write_text("[repair]\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    status = main(["repair", "issue", "owner/repo#1"])

    captured = capsys.readouterr()
    assert status == 1
    assert "Unknown config section [repair]" in captured.err


def test_invalid_cli_repair_agent_returns_shared_validator_error(capsys, tmp_path: Path) -> None:
    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path),
            "--repair-agent",
            "openai",
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "Invalid value for 'repair_agent' (--repair-agent):" in captured.err
    assert "'openai'" in captured.err
    assert "Expected one of: opencode, none, vercel-ai" in captured.err
    assert "invalid choice" not in captured.err
    assert "usage:" not in captured.err


def test_missing_repo_path_error_lists_supported_config_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    status = main(["repair", "issue", "owner/repo#1"])

    captured = capsys.readouterr()
    assert status == 1
    assert "./.precision-squad.toml" in captured.err
    assert "./.precision-squad/precision-squad.toml" in captured.err
    assert "active command's discovery root" in captured.err


def test_publish_run_uses_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    runs_dir = tmp_path / "runs-from-config"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (tmp_path / ".precision-squad.toml").write_text(
        f'[publish.run]\nruns_dir = "{runs_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {"owner": "owner", "repo": "repo", "number": 1},
                    "title": "Issue",
                    "body": "Body",
                    "labels": [],
                    "html_url": "https://github.com/owner/repo/issues/1",
                },
                "summary": "Summary",
                "problem_statement": "Problem",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-plan.json").write_text(
        json.dumps({"status": "draft_pr", "title": "title", "body": "body", "reason_codes": []}),
        encoding="utf-8",
    )
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "owner/repo#1",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-result.json").write_text(
        json.dumps({"status": "dry_run", "target": "draft_pr", "summary": "dry run"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "precision_squad.cli.execute_publish_plan",
        lambda intake, plan, publish, run_dir: PublishResult(
            status="dry_run", target=plan.status, summary="dry run", url=None
        ),
    )
    monkeypatch.setattr("precision_squad.cli._run_post_publish_review_if_needed", lambda **kwargs: None)

    status = main(["publish", "run", "run-123"])

    captured = capsys.readouterr()
    assert status == 0
    assert "Run ID: run-123" in captured.out


def test_plan_run_uses_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    runs_dir = tmp_path / "runs-from-config"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (tmp_path / ".precision-squad.toml").write_text(
        f'[plan]\nruns_dir = "{runs_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "owner/repo#1",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")

    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.persist_approved_plan_for_planning",
        lambda self, *, params: run_dir / "approved-plan.json",
    )

    status = main(["plan", "run-123", "--approved-plan-path", str(plan_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert "Run ID: run-123" in captured.out


def test_implement_run_prints_local_only_stage_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        "precision_squad.cli.RunCoordinator.implement_run",
        lambda self, *, params, dependencies: __import__(
            "precision_squad.coordinator", fromlist=["ImplementRunReport"]
        ).ImplementRunReport(
            intake=IssueIntake(
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
            ),
            run_record=RunRecord(
                run_id="run-123",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs" / "run-123"),
            ),
            execution_result=ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="Execution completed.",
                detail_codes=(),
            ),
            evaluation_result=EvaluationResult(
                status="success",
                summary="Evaluation succeeded.",
                detail_codes=(),
            ),
            governance_verdict=GovernanceVerdict(
                status="approved",
                summary="Approved",
                reason_codes=(),
            ),
            repair_result=None,
            baseline_qa_result=None,
            qa_result=None,
            exit_code=0,
        ),
    )

    status = main(
        [
            "implement",
            "run-123",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Execution Status: completed" in captured.out
    assert "Governance: approved" in captured.out
    assert "Publish Plan:" not in captured.out
    assert "Publish Result:" not in captured.out


def test_implement_run_uses_config_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    repo_path = tmp_path / "repo-from-config"
    repo_path.mkdir()
    runs_dir = tmp_path / "runs-from-config"
    (tmp_path / ".precision-squad.toml").write_text(
        (
            "[implement]\n"
            f'repo_path = "{repo_path.as_posix()}"\n'
            f'runs_dir = "{runs_dir.as_posix()}"\n'
            'repair_agent = "none"\n'
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    captured: dict[str, str] = {}

    def fake_implement_run(self, *, params, dependencies):
        del self, dependencies
        captured["repo_path"] = str(params.repo_path)
        captured["runs_dir"] = str(params.runs_dir)
        return __import__("precision_squad.coordinator", fromlist=["ImplementRunReport"]).ImplementRunReport(
            intake=IssueIntake(
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
            ),
            run_record=RunRecord(
                run_id="run-123",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(runs_dir / "run-123"),
            ),
            execution_result=ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="Execution completed.",
                detail_codes=(),
            ),
            evaluation_result=EvaluationResult(
                status="success",
                summary="Evaluation succeeded.",
                detail_codes=(),
            ),
            governance_verdict=GovernanceVerdict(
                status="approved",
                summary="Approved",
                reason_codes=(),
            ),
            exit_code=0,
        )

    monkeypatch.setattr("precision_squad.cli.RunCoordinator.implement_run", fake_implement_run)

    status = main(["implement", "run-123"])

    captured_out = capsys.readouterr()
    assert status == 0
    assert Path(captured["repo_path"]) == repo_path
    assert Path(captured["runs_dir"]) == runs_dir
    assert "Run ID: run-123" in captured_out.out


def test_review_plan_end_to_end_persists_approved_plan_review(capsys, tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    request = RunRequest(
        issue_ref="cracklings3d/precision-squad#70",
        runs_dir=str(runs_dir),
    )
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "precision-squad", 70),
            title="Add the review plan stage gate",
            body="Persist a plan review artifact.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/precision-squad/issues/70",
        ),
        summary="Add the review plan stage gate",
        problem_statement="Persist a plan review artifact.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    record = store.create_run(request, intake)
    run_dir = Path(record.run_dir)
    (run_dir / "issue-review.json").write_text(
        json.dumps(
            {
                "run_id": record.run_id,
                "issue_ref": "cracklings3d/precision-squad#70",
                "review_status": "approved",
                "summary": "Planning may proceed because issue-draft.json passed the local planner-safety review.",
                "feedback": [],
                "provenance": {
                    "source_artifact": "issue-draft.json",
                    "run_id": record.run_id,
                    "issue_ref": "cracklings3d/precision-squad#70",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/precision-squad#70",
                "plan_summary": "Keep the implement ingress narrowly gated.",
                "implementation_steps": ["Add review plan command"],
                "named_references": [],
                "retrieval_surface_summary": "src/precision_squad/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    status = main(["review", "plan", record.run_id, "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    payload = json.loads((run_dir / "plan-review.json").read_text(encoding="utf-8"))
    assert status == 0
    assert payload["review_status"] == "approved"
    assert payload["provenance"]["source_artifact"] == "approved-plan.json"
    assert "Review Status: approved" in captured.out


def test_review_plan_end_to_end_persists_changes_requested_when_plan_summary_surface_missing(
    capsys, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/precision-squad#70",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "issue-review.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/precision-squad#70",
                "review_status": "approved",
                "summary": "Planning may proceed because issue-draft.json passed the local planner-safety review.",
                "feedback": [],
                "provenance": {
                    "source_artifact": "issue-draft.json",
                    "run_id": "run-123",
                    "issue_ref": "cracklings3d/precision-squad#70",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/precision-squad#70",
                "plan_summary": "Keep the implement ingress narrowly gated.",
                "implementation_steps": ["Add review plan command"],
                "named_references": [],
                "retrieval_surface_summary": "",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    status = main(["review", "plan", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    payload = json.loads((run_dir / "plan-review.json").read_text(encoding="utf-8"))
    assert status == 2
    assert payload["review_status"] == "changes_requested"
    assert payload["feedback"][0]["code"] == "missing_retrieval_surface_summary"
    assert "Review Status: changes_requested" in captured.out


def test_review_plan_end_to_end_persists_blocked_when_approved_plan_missing(
    capsys, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/precision-squad#70",
                "status": "runnable",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:00:00Z",
                "run_dir": str(run_dir),
                "attempt": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "issue-review.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/precision-squad#70",
                "review_status": "approved",
                "summary": "Planning may proceed because issue-draft.json passed the local planner-safety review.",
                "feedback": [],
                "provenance": {
                    "source_artifact": "issue-draft.json",
                    "run_id": "run-123",
                    "issue_ref": "cracklings3d/precision-squad#70",
                },
            }
        ),
        encoding="utf-8",
    )

    status = main(["review", "plan", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    payload = json.loads((run_dir / "plan-review.json").read_text(encoding="utf-8"))
    assert status == 3
    assert payload["review_status"] == "blocked"
    assert payload["feedback"][0]["code"] == "approved_plan_missing"
    assert "Review Status: blocked" in captured.out


def test_install_skill_uses_config_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (tmp_path / ".precision-squad.toml").write_text(
        f'[install-skill]\nproject_root = "{project_root.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    status = main(["install-skill"])

    captured = capsys.readouterr()
    assert status == 0
    assert (project_root / "SKILL.md").exists()
    assert "Installed skill:" in captured.out


def test_repair_issue_no_publish_cli_overrides_true_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "repo-from-config"
    runs_dir = tmp_path / "runs-from-config"
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")
    (tmp_path / ".precision-squad.toml").write_text(
        (
            "[repair.issue]\n"
            f'repo_path = "{repo_path.as_posix()}"\n'
            f'runs_dir = "{runs_dir.as_posix()}"\n'
            "publish = true\n"
            'repair_agent = "none"\n'
            f'approved_plan_path = "{plan_path.as_posix()}"\n'
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Example issue",
            body="Example body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Example summary",
        problem_statement="Example problem",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    captured_params: dict[str, object] = {}

    def fake_repair_issue(self, *, params, intake, dependencies):
        del self, dependencies
        captured_params["publish"] = params.publish
        return RepairIssueReport(
            intake=intake,
            run_record=RunRecord(
                run_id="run-1",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(tmp_path / "runs-from-config" / "run-1"),
            ),
            execution_result=ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="Stub execution completed.",
                detail_codes=(),
            ),
            evaluation_result=EvaluationResult(
                status="success",
                summary="Stub evaluation completed.",
                detail_codes=(),
            ),
            governance_verdict=GovernanceVerdict(
                status="approved",
                summary="Approved",
                reason_codes=(),
            ),
            publish_plan=PublishPlan(
                status="draft_pr",
                title="title",
                body="body",
                reason_codes=(),
            ),
            publish_result=PublishResult(
                status="dry_run",
                target="draft_pr",
                summary="dry run",
                url=None,
            ),
            repair_result=None,
            qa_result=None,
            post_publish_review_result=None,
            exit_code=0,
        )

    monkeypatch.setattr("precision_squad.cli.RunCoordinator.repair_issue", fake_repair_issue)

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--no-publish",
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    assert status == 0
    assert captured_params["publish"] is False


def test_repair_issue_uses_explicit_repo_path_as_config_discovery_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_path = tmp_path / "target-repo"
    repo_path.mkdir()
    plan_path = repo_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "owner/repo#1",
                "plan_summary": "Repair the issue.",
                "implementation_steps": ["Apply minimal change"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    (workspace / ".precision-squad.toml").write_text(
        (
            "[repair.issue]\n"
            f'runs_dir = "{(workspace / "runs-from-cwd").as_posix()}"\n'
            'repair_agent = "vercel-ai"\n'
        ),
        encoding="utf-8",
    )
    (repo_path / ".precision-squad.toml").write_text(
        (
            "[repair.issue]\n"
            f'runs_dir = "{(repo_path / "runs-from-repo").as_posix()}"\n'
            'repair_agent = "none"\n'
            f'approved_plan_path = "{plan_path.as_posix()}"\n'
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)

    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Example issue",
            body="Example body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Example summary",
        problem_statement="Example problem",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    captured_params: dict[str, object] = {}

    def fake_repair_issue(self, *, params, intake, dependencies):
        del self, dependencies
        captured_params["runs_dir"] = params.runs_dir
        captured_params["repair_agent"] = params.repair_agent
        return RepairIssueReport(
            intake=intake,
            run_record=RunRecord(
                run_id="run-1",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(workspace / "runs-from-cwd" / "run-1"),
            ),
            execution_result=ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="Stub execution completed.",
                detail_codes=(),
            ),
            evaluation_result=EvaluationResult(
                status="success",
                summary="Stub evaluation completed.",
                detail_codes=(),
            ),
            governance_verdict=GovernanceVerdict(
                status="approved",
                summary="Approved",
                reason_codes=(),
            ),
            publish_plan=PublishPlan(
                status="draft_pr",
                title="title",
                body="body",
                reason_codes=(),
            ),
            publish_result=PublishResult(
                status="dry_run",
                target="draft_pr",
                summary="dry run",
                url=None,
            ),
            repair_result=None,
            qa_result=None,
            post_publish_review_result=None,
            exit_code=0,
        )

    monkeypatch.setattr("precision_squad.cli.RunCoordinator.repair_issue", fake_repair_issue)

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(repo_path),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    assert status == 0
    assert captured_params["runs_dir"] == repo_path / "runs-from-repo"
    assert captured_params["repair_agent"] == "none"


def test_install_skill_uses_explicit_project_root_as_config_discovery_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    skill_path = project_root / "SKILL.md"
    skill_path.write_text("existing\n", encoding="utf-8")

    (project_root / ".precision-squad.toml").write_text(
        "[install-skill]\nforce = true\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)

    status = main(["install-skill", "--project-root", str(project_root)])

    captured = capsys.readouterr()
    assert status == 0
    assert skill_path.exists()
    assert "Installed skill:" in captured.out


def test_run_issue_with_approved_plan_path_persists_approved_plan(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Stub execution completed.",
            detail_codes=(),
        ),
    )

    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Add --version flag using click.",
                "implementation_steps": ["Add click.option('--version')", "Bump __version__"],
                "named_references": ["src/cli.py"],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    run_dir_line = next(line for line in captured.out.splitlines() if line.startswith("Run Dir:"))
    run_dir = Path(run_dir_line.removeprefix("Run Dir:").strip())

    assert status == 0
    assert (run_dir / "approved-plan.json").exists()
    plan_payload = json.loads((run_dir / "approved-plan.json").read_text(encoding="utf-8"))
    assert plan_payload["issue_ref"] == "cracklings3d/markdown-pdf-renderer#9"
    assert plan_payload["plan_summary"] == "Add --version flag using click."
    assert plan_payload["implementation_steps"] == [
        "Add click.option('--version')",
        "Bump __version__",
    ]
    assert plan_payload["named_references"] == [
        {"name": "src/cli.py", "reference_type": "file", "description": ""}
    ]


def test_run_issue_with_mismatched_approved_plan_issue_ref_raises(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#99",
                "plan_summary": "Different issue plan",
                "implementation_steps": ["Step 1"],
                "named_references": [],
                "retrieval_surface_summary": "",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    assert status == 1
    captured = capsys.readouterr()
    assert "does not match expected issue_ref" in captured.err


def test_run_issue_requires_approved_plan_path_for_fresh_runs(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    status = main(
        [
            "repair",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "require --approved-plan-path" in captured.err
    assert not (tmp_path / "runs").exists()


def test_run_issue_explicit_fresh_without_approved_plan_path_fails_before_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "precision_squad.cli.load_issue_intake",
        lambda _: (_ for _ in ()).throw(AssertionError("intake should not run")),
    )

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--fresh",
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "require --approved-plan-path" in captured.err


def test_run_issue_retry_from_missing_run_fails_before_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "precision_squad.cli.load_issue_intake",
        lambda _: (_ for _ in ()).throw(AssertionError("intake should not run")),
    )

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--retry-from",
            "missing-run",
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "Retry run not found" in captured.err


def test_run_issue_retry_from_other_issue_fails_before_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    runs_dir.mkdir(parents=True)
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 2),
            title="Other issue",
            body="Body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/2",
        ),
        summary="Other issue",
        problem_statement="Body",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    record = store.create_run(RunRequest(issue_ref="Owner/Repo#2", runs_dir=str(runs_dir)), intake)
    monkeypatch.setattr(
        "precision_squad.cli.load_issue_intake",
        lambda _: (_ for _ in ()).throw(AssertionError("intake should not run")),
    )

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(runs_dir),
            "--retry-from",
            record.run_id,
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "belongs to" in captured.err


def test_run_issue_non_interactive_ambiguous_prior_runs_requires_explicit_selection(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    runs_dir.mkdir(parents=True)
    intake_payload = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Issue",
            body="Body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Issue",
        problem_statement="Body",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    store.create_run(
        RunRequest(issue_ref="Owner/Repo#1", runs_dir=str(runs_dir)), intake_payload
    )
    monkeypatch.setattr(
        "precision_squad.cli._repair_issue_prompt_is_interactive",
        lambda: False,
    )
    monkeypatch.setattr(
        "precision_squad.cli.load_issue_intake",
        lambda _: (_ for _ in ()).throw(AssertionError("intake should not run")),
    )

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(runs_dir),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "--retry-from <run-id>" in captured.err
    assert "--fresh" in captured.err


def test_run_issue_prompt_selected_fresh_without_plan_fails_before_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    runs_dir.mkdir(parents=True)
    intake_payload = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Issue",
            body="Body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Issue",
        problem_statement="Body",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    store.create_run(
        RunRequest(issue_ref="owner/repo#1", runs_dir=str(runs_dir)), intake_payload
    )
    monkeypatch.setattr("precision_squad.cli._repair_issue_prompt_is_interactive", lambda: True)
    monkeypatch.setattr("precision_squad.cli._prompt_for_run_selection", lambda runs: "fresh")
    monkeypatch.setattr(
        "precision_squad.cli.load_issue_intake",
        lambda _: (_ for _ in ()).throw(AssertionError("intake should not run")),
    )

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(runs_dir),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "require --approved-plan-path" in captured.err


def test_run_issue_prompt_selected_retry_can_continue_without_new_plan_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    runs_dir.mkdir(parents=True)
    intake_payload = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Issue",
            body="Body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Issue",
        problem_statement="Body",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    record = store.create_run(
        RunRequest(issue_ref="Owner/Repo#1", runs_dir=str(runs_dir)), intake_payload
    )
    store.write_approved_plan(Path(record.run_dir), ApprovedPlan(
        issue_ref="Owner/Repo#1",
        plan_summary="Plan",
        implementation_steps=("Step",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    ))
    monkeypatch.setattr("precision_squad.cli._repair_issue_prompt_is_interactive", lambda: True)
    monkeypatch.setattr("precision_squad.cli._prompt_for_run_selection", lambda runs: record.run_id)
    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake_payload)

    captured: dict[str, object] = {}

    def fake_repair_issue(self, *, params, intake, dependencies):
        del self, intake, dependencies
        captured["retry_from"] = params.retry_from
        return RepairIssueReport(
            intake=intake_payload,
            run_record=RunRecord(
                run_id="run-next",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(runs_dir / "run-next"),
            ),
            execution_result=ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="done",
                detail_codes=(),
            ),
            evaluation_result=EvaluationResult(status="success", summary="ok", detail_codes=()),
            governance_verdict=GovernanceVerdict(status="approved", summary="ok", reason_codes=()),
            publish_plan=PublishPlan(status="draft_pr", title="t", body="b", reason_codes=()),
            publish_result=PublishResult(status="dry_run", target="draft_pr", summary="ok", url=None),
        )

    monkeypatch.setattr("precision_squad.cli.RunCoordinator.repair_issue", fake_repair_issue)

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(runs_dir),
        ]
    )

    assert status == 0
    assert captured["retry_from"] == record.run_id


def test_run_issue_explicit_fresh_bypasses_ambiguity_and_calls_coordinator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    store = RunStore(runs_dir)
    runs_dir.mkdir(parents=True)
    prior_intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("owner", "repo", 1),
            title="Issue",
            body="Body",
            labels=(),
            html_url="https://github.com/owner/repo/issues/1",
        ),
        summary="Issue",
        problem_statement="Body",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    store.create_run(RunRequest(issue_ref="Owner/Repo#1", runs_dir=str(runs_dir)), prior_intake)
    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: prior_intake)
    plan_path = _write_valid_plan(tmp_path, issue_ref="owner/repo#1")

    captured: dict[str, object] = {}

    def fake_repair_issue(self, *, params, intake, dependencies):
        del self, intake, dependencies
        captured["retry_from"] = params.retry_from
        return RepairIssueReport(
            intake=prior_intake,
            run_record=RunRecord(
                run_id="run-1",
                issue_ref="owner/repo#1",
                status="runnable",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T00:00:00Z",
                run_dir=str(runs_dir / "run-1"),
            ),
            execution_result=ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="done",
                detail_codes=(),
            ),
            evaluation_result=EvaluationResult(status="success", summary="ok", detail_codes=()),
            governance_verdict=GovernanceVerdict(status="approved", summary="ok", reason_codes=()),
            publish_plan=PublishPlan(status="draft_pr", title="t", body="b", reason_codes=()),
            publish_result=PublishResult(status="dry_run", target="draft_pr", summary="ok", url=None),
        )

    monkeypatch.setattr("precision_squad.cli.RunCoordinator.repair_issue", fake_repair_issue)

    status = main(
        [
            "repair",
            "issue",
            "owner/repo#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(runs_dir),
            "--fresh",
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    assert status == 0
    assert captured["retry_from"] is None


def test_prompt_for_run_selection_reprompts_on_invalid_input(
    capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = [
        RunRecord(
            run_id="run-2",
            issue_ref="owner/repo#1",
            status="runnable",
            created_at="2026-05-02T00:00:00Z",
            updated_at="2026-05-02T00:00:00Z",
            run_dir="/tmp/run-2",
            attempt=2,
        )
    ]
    responses = iter(["bad", "run-2"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))

    choice = _prompt_for_run_selection(runs)

    captured = capsys.readouterr()
    assert choice == "run-2"
    assert "Invalid selection" in captured.out


def test_prompt_for_run_selection_aborts_on_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = [
        RunRecord(
            run_id="run-2",
            issue_ref="owner/repo#1",
            status="runnable",
            created_at="2026-05-02T00:00:00Z",
            updated_at="2026-05-02T00:00:00Z",
            run_dir="/tmp/run-2",
            attempt=2,
        )
    ]
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(ValueError, match="aborted"):
        _prompt_for_run_selection(runs)


def test_repair_issue_prompt_is_interactive_requires_both_ttys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert _repair_issue_prompt_is_interactive() is False


def test_repair_issue_help_mentions_fresh_run_approved_plan_requirement(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["repair", "issue", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "Required for fresh" in captured.out
    assert "retries may omit it" in captured.out


def test_repair_issue_parser_rejects_fresh_with_retry_from(capsys, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "repair",
                "issue",
                "owner/repo#1",
                "--repo-path",
                str(tmp_path),
                "--fresh",
                "--retry-from",
                "run-1",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "not allowed with argument" in captured.err


def test_load_approved_plan_rejects_missing_retrieval_surface_summary(
    capsys, tmp_path: Path
) -> None:
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "A valid plan",
                "implementation_steps": ["Step 1"],
                "named_references": [],
                "approved": True,
            }
        ),
        encoding="utf-8",
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "retrieval_surface_summary" in captured.err
    assert not (tmp_path / "runs").exists()


def test_load_approved_plan_rejects_non_object_json_payload(capsys, tmp_path: Path) -> None:
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text("[]\n", encoding="utf-8")

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "Expected JSON object" in captured.err
    assert not (tmp_path / "runs").exists()


def _write_valid_plan(tmp_path: Path, *, issue_ref: str) -> Path:
    plan_path = tmp_path / f"{issue_ref.split('#')[-1]}-approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": issue_ref,
                "plan_summary": "Approved plan summary.",
                "implementation_steps": ["Implement the change"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    return plan_path


def test_load_approved_plan_rejects_missing_plan_summary(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "",
                "implementation_steps": ["Step 1"],
                "named_references": [],
                "retrieval_surface_summary": "",
            }
        ),
        encoding="utf-8",
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    assert status == 1
    captured = capsys.readouterr()
    assert "non-empty" in captured.err.lower() or "plan_summary" in captured.err.lower()


def test_load_approved_plan_rejects_missing_implementation_steps(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "A valid plan",
                "implementation_steps": [],
                "named_references": [],
                "retrieval_surface_summary": "",
            }
        ),
        encoding="utf-8",
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--approved-plan-path",
            str(plan_path),
        ]
    )

    assert status == 1
    captured = capsys.readouterr()
    assert "implementation steps" in captured.err.lower()


class TestLoadApprovedPlanValidation:
    def test_rejects_missing_issue_ref(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "approved-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "plan_summary": "A plan",
                    "implementation_steps": ["Step 1"],
                    "named_references": [],
                    "retrieval_surface_summary": "",
                    "approved": True,
                }
            ),
            encoding="utf-8",
        )
        from precision_squad.cli import _load_approved_plan

        with pytest.raises(ValueError, match="issue_ref"):
            _load_approved_plan(plan_path, "owner/repo#1")

    def test_rejects_wrong_issue_ref(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "approved-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "issue_ref": "owner/repo#99",
                    "plan_summary": "A plan",
                    "implementation_steps": ["Step 1"],
                    "named_references": [],
                    "retrieval_surface_summary": "",
                    "approved": True,
                }
            ),
            encoding="utf-8",
        )
        from precision_squad.cli import _load_approved_plan

        with pytest.raises(ValueError, match="does not match"):
            _load_approved_plan(plan_path, "owner/repo#1")

    def test_rejects_empty_plan_summary(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "approved-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "issue_ref": "owner/repo#1",
                    "plan_summary": "   ",
                    "implementation_steps": ["Step 1"],
                    "named_references": [],
                    "retrieval_surface_summary": "",
                    "approved": True,
                }
            ),
            encoding="utf-8",
        )
        from precision_squad.cli import _load_approved_plan

        with pytest.raises(ValueError, match="plan_summary"):
            _load_approved_plan(plan_path, "owner/repo#1")

    def test_rejects_empty_implementation_steps(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "approved-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "issue_ref": "owner/repo#1",
                    "plan_summary": "A plan",
                    "implementation_steps": [],
                    "named_references": [],
                    "retrieval_surface_summary": "",
                    "approved": True,
                }
            ),
            encoding="utf-8",
        )
        from precision_squad.cli import _load_approved_plan

        with pytest.raises(ValueError, match="implementation steps"):
            _load_approved_plan(plan_path, "owner/repo#1")

    def test_rejects_unapproved_plan(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "approved-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "issue_ref": "owner/repo#1",
                    "plan_summary": "A plan",
                    "implementation_steps": ["Step 1"],
                    "named_references": [],
                    "retrieval_surface_summary": "",
                    "approved": False,
                }
            ),
            encoding="utf-8",
        )
        from precision_squad.cli import _load_approved_plan

        with pytest.raises(ValueError, match="approved.*true"):
            _load_approved_plan(plan_path, "owner/repo#1")

    def test_rejects_missing_named_references(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "approved-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "issue_ref": "owner/repo#1",
                    "plan_summary": "A plan",
                    "implementation_steps": ["Step 1"],
                    "retrieval_surface_summary": "",
                    "approved": True,
                }
            ),
            encoding="utf-8",
        )
        from precision_squad.cli import _load_approved_plan

        with pytest.raises(ValueError, match="named_references"):
            _load_approved_plan(plan_path, "owner/repo#1")

    def test_rejects_non_string_implementation_step(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "approved-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "issue_ref": "owner/repo#1",
                    "plan_summary": "A plan",
                    "implementation_steps": [1],
                    "named_references": [],
                    "retrieval_surface_summary": "",
                    "approved": True,
                }
            ),
            encoding="utf-8",
        )
        from precision_squad.cli import _load_approved_plan

        with pytest.raises(ValueError, match=r"implementation_steps\[1\]"):
            _load_approved_plan(plan_path, "owner/repo#1")

    def test_returns_approved_plan(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "approved-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "issue_ref": "owner/repo#1",
                    "plan_summary": "Fix the bug",
                    "implementation_steps": ["Step 1", "Step 2"],
                    "named_references": ["src/main.py"],
                    "retrieval_surface_summary": "src/",
                    "approved": True,
                }
            ),
            encoding="utf-8",
        )
        from precision_squad.cli import _load_approved_plan

        plan = _load_approved_plan(plan_path, "owner/repo#1")
        assert isinstance(plan, ApprovedPlan)
        assert plan.issue_ref == "owner/repo#1"
        assert plan.plan_summary == "Fix the bug"
        assert plan.implementation_steps == ("Step 1", "Step 2")
        assert tuple(ref.name for ref in plan.named_references) == ("src/main.py",)
        assert plan.retrieval_surface_summary == "src/"
        assert plan.approved is True
