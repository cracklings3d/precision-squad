"""Integration tests: stage artifact persistence and cross-stage handoff.

Verifies each stage command persists its output artifact to
`.precision-squad/runs/{run-id}/` and that the artifact is consumable
as handoff input to the next stage command without reconstruction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad.coordinator import (
    CreateIssueParams,
    ImplementRunParams,
    PersistApprovedPlanParams,
    RepairIssueParams,
    ReviewImplParams,
    ReviewIssueParams,
    ReviewPlanParams,
    RunCoordinator,
)
from precision_squad.models import (
    ApprovedPlan,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    NamedReference,
)
from precision_squad.run_store import RunStore
from tests.integration.conftest import StubRepairAdapter
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
# Test 1: issue-draft.json from create issue
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_issue_draft_persists_to_runs_dir(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """After create issue, issue-draft.json exists with title, body, created_at."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    coordinator = RunCoordinator()
    report = coordinator.create_issue(
        params=CreateIssueParams(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=runs_dir,
        ),
        intake=_runnable_intake(),
    )

    run_dir = Path(report.run_record.run_dir)
    artifact_path = run_dir / "issue-draft.json"

    assert artifact_path.exists(), "issue-draft.json should be written by create issue"

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert "title" in payload, "issue-draft.json must contain title"
    assert "summary" in payload, "issue-draft.json must contain summary"
    # provenance is required
    assert "provenance" in payload, "issue-draft.json must contain provenance"
    assert payload["title"] == "[Enhancement] Add --version flag to CLI"


# ---------------------------------------------------------------------------
# Test 2: issue-review.json from review issue
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_issue_review_persists(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """After review issue, issue-review.json exists with verdict field."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    coordinator = RunCoordinator()
    create_report = coordinator.create_issue(
        params=CreateIssueParams(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=runs_dir,
        ),
        intake=_runnable_intake(),
    )

    review_report = coordinator.review_issue(
        params=ReviewIssueParams(
            run_id=create_report.run_record.run_id,
            runs_dir=runs_dir,
        )
    )

    run_dir = Path(create_report.run_record.run_dir)
    artifact_path = run_dir / "issue-review.json"

    assert artifact_path.exists(), "issue-review.json should be written by review issue"

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert "review_status" in payload, "issue-review.json must contain review_status (verdict)"


# ---------------------------------------------------------------------------
# Test 3: approved-plan.json from persist approved plan (plan stage)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_approved_plan_persists(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """After plan with approved verdict, approved-plan.json exists with plan content."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    coordinator = RunCoordinator()
    create_report = coordinator.create_issue(
        params=CreateIssueParams(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=runs_dir,
        ),
        intake=_runnable_intake(),
    )

    # Approve the issue review
    run_dir = Path(create_report.run_record.run_dir)
    store = RunStore(runs_dir)
    from precision_squad.models import IssueReview, IssueReviewProvenance

    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=create_report.run_record.run_id,
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            review_status="approved",
            summary="Planning may proceed.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=create_report.run_record.run_id,
                issue_ref="cracklings3d/markdown-pdf-renderer#9",
            ),
        ),
    )

    # Persist approved plan
    plan = ApprovedPlan(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        plan_summary="Add --version flag to CLI.",
        implementation_steps=("Implement the flag.",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )
    coordinator.persist_approved_plan_for_planning(
        params=PersistApprovedPlanParams(
            run_id=create_report.run_record.run_id,
            runs_dir=runs_dir,
            approved_plan=plan,
        )
    )

    artifact_path = run_dir / "approved-plan.json"

    assert artifact_path.exists(), "approved-plan.json should be written by persist approved plan"

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert "issue_ref" in payload, "approved-plan.json must contain issue_ref"
    assert "plan_summary" in payload, "approved-plan.json must contain plan_summary"
    assert payload["approved"] is True, "approved-plan.json must have approved: true"


# ---------------------------------------------------------------------------
# Test 4: plan-review.json from review plan
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_plan_review_persists(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """After review plan, plan-review.json exists."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    coordinator = RunCoordinator()
    create_report = coordinator.create_issue(
        params=CreateIssueParams(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=runs_dir,
        ),
        intake=_runnable_intake(),
    )

    run_dir = Path(create_report.run_record.run_dir)
    store = RunStore(runs_dir)

    # Write approved issue review
    from precision_squad.models import IssueReview, IssueReviewProvenance

    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=create_report.run_record.run_id,
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            review_status="approved",
            summary="Planning may proceed.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=create_report.run_record.run_id,
                issue_ref="cracklings3d/markdown-pdf-renderer#9",
            ),
        ),
    )

    # Write approved plan
    plan = ApprovedPlan(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        plan_summary="Add --version flag to CLI.",
        implementation_steps=("Implement the flag",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )
    store.write_approved_plan(run_dir, plan)

    # Run review plan
    review_plan_report = coordinator.review_plan(
        params=ReviewPlanParams(
            run_id=create_report.run_record.run_id,
            runs_dir=runs_dir,
        )
    )

    artifact_path = run_dir / "plan-review.json"

    assert artifact_path.exists(), "plan-review.json should be written by review plan"

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert "review_status" in payload, "plan-review.json must contain review_status"


# ---------------------------------------------------------------------------
# Test 5: impl-review.json from review impl
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_impl_review_persists(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """After review impl, impl-review.json exists and contains verdict."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Set up run with all required artifacts
    store = RunStore(runs_dir)
    intake = _runnable_intake()
    record = store.create_run(
        request=__import__("precision_squad.models", fromlist=["RunRequest"]).RunRequest(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=str(runs_dir),
        ),
        intake=intake,
    )
    run_dir = Path(record.run_dir)

    from precision_squad.models import IssueReview, IssueReviewProvenance

    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=record.run_id,
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            review_status="approved",
            summary="Planning may proceed.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=record.run_id,
                issue_ref="cracklings3d/markdown-pdf-renderer#9",
            ),
        ),
    )

    plan = ApprovedPlan(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        plan_summary="Add --version flag to CLI.",
        implementation_steps=("Implement the flag",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )
    store.write_approved_plan(run_dir, plan)

    from precision_squad.models import PlanReview, PlanReviewProvenance

    store.write_plan_review(
        run_dir,
        PlanReview(
            run_id=record.run_id,
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            review_status="approved",
            summary="Plan review approved.",
            feedback=(),
            provenance=PlanReviewProvenance(
                source_artifact="approved-plan.json",
                run_id=record.run_id,
                issue_ref="cracklings3d/markdown-pdf-renderer#9",
            ),
        ),
    )

    from precision_squad.models import PublishPlan, PublishResult

    store.write_publish_plan(
        run_dir,
        PublishPlan(
            status="draft_pr",
            title="Add --version flag",
            body="body",
            reason_codes=(),
            pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/1",
            pull_number=1,
        ),
    )
    store.write_publish_result(
        run_dir,
        PublishResult(
            status="published",
            target="draft_pr",
            summary="Published.",
            url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/1",
            pull_number=1,
        ),
    )

    deps = _ApprovedTestDependencies(stub_repair_adapter)

    review_impl_report = RunCoordinator().review_impl(
        params=ReviewImplParams(
            run_id=record.run_id,
            runs_dir=runs_dir,
            review_model=None,
        ),
        dependencies=deps,
    )

    artifact_path = run_dir / "impl-review.json"

    assert artifact_path.exists(), "impl-review.json should be written by review impl"

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert "review_status" in payload, "impl-review.json must contain review_status (verdict)"


# ---------------------------------------------------------------------------
# Test 6: post-publish-review-result.json from post-publish review
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_post_publish_review_result_persists(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """After post-publish review, post-publish-review-result.json exists."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Set up run with all required artifacts
    store = RunStore(runs_dir)
    intake = _runnable_intake()
    record = store.create_run(
        request=__import__("precision_squad.models", fromlist=["RunRequest"]).RunRequest(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=str(runs_dir),
        ),
        intake=intake,
    )
    run_dir = Path(record.run_dir)

    from precision_squad.models import IssueReview, IssueReviewProvenance

    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=record.run_id,
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            review_status="approved",
            summary="Planning may proceed.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=record.run_id,
                issue_ref="cracklings3d/markdown-pdf-renderer#9",
            ),
        ),
    )

    plan = ApprovedPlan(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        plan_summary="Add --version flag to CLI.",
        implementation_steps=("Implement the flag",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )
    store.write_approved_plan(run_dir, plan)

    from precision_squad.models import PlanReview, PlanReviewProvenance

    store.write_plan_review(
        run_dir,
        PlanReview(
            run_id=record.run_id,
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            review_status="approved",
            summary="Plan review approved.",
            feedback=(),
            provenance=PlanReviewProvenance(
                source_artifact="approved-plan.json",
                run_id=record.run_id,
                issue_ref="cracklings3d/markdown-pdf-renderer#9",
            ),
        ),
    )

    from precision_squad.models import PublishPlan, PublishResult

    store.write_publish_plan(
        run_dir,
        PublishPlan(
            status="draft_pr",
            title="Add --version flag",
            body="body",
            reason_codes=(),
            pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/1",
            pull_number=1,
        ),
    )
    store.write_publish_result(
        run_dir,
        PublishResult(
            status="published",
            target="draft_pr",
            summary="Published.",
            url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/1",
            pull_number=1,
        ),
    )

    deps = _ApprovedTestDependencies(stub_repair_adapter)

    review_impl_report = RunCoordinator().review_impl(
        params=ReviewImplParams(
            run_id=record.run_id,
            runs_dir=runs_dir,
            review_model=None,
        ),
        dependencies=deps,
    )

    artifact_path = run_dir / "post-publish-review-result.json"

    assert artifact_path.exists(), (
        "post-publish-review-result.json should be written by review impl"
    )


# ---------------------------------------------------------------------------
# Test 7: governance-verdict.json from full repair_issue flow
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_governance_verdict_persists(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """After governance check via full repair_issue flow, governance-verdict.json exists with status: approved."""
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
    artifact_path = run_dir / "governance-verdict.json"

    assert artifact_path.exists(), (
        "governance-verdict.json should be written by repair_issue"
    )

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert "status" in payload, "governance-verdict.json must contain status"
    assert payload["status"] == "approved", (
        "governance-verdict.json status must be approved for a passing run"
    )


# ---------------------------------------------------------------------------
# Cross-stage handoff tests: artifact is consumable by next stage
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_issue_draft_consumable_by_review_stage(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """issue-draft.json is consumable by the review stage contract loader."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    coordinator = RunCoordinator()
    create_report = coordinator.create_issue(
        params=CreateIssueParams(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=runs_dir,
        ),
        intake=_runnable_intake(),
    )

    run_dir = Path(create_report.run_record.run_dir)
    artifact_path = run_dir / "issue-draft.json"

    # Load via RunStore to verify consumability
    loaded = RunStore.load_issue_draft_from_dir(run_dir)
    assert loaded.title == "[Enhancement] Add --version flag to CLI"
    assert loaded.summary == "Add --version flag to CLI"


@pytest.mark.integration
def test_issue_review_consumable_by_plan_stage(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """issue-review.json is consumable by the plan stage."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    coordinator = RunCoordinator()
    create_report = coordinator.create_issue(
        params=CreateIssueParams(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=runs_dir,
        ),
        intake=_runnable_intake(),
    )

    review_report = coordinator.review_issue(
        params=ReviewIssueParams(
            run_id=create_report.run_record.run_id,
            runs_dir=runs_dir,
        )
    )

    run_dir = Path(create_report.run_record.run_dir)

    # Load via RunStore to verify consumability
    loaded = RunStore.load_issue_review(
        run_dir,
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        expected_run_id=create_report.run_record.run_id,
    )
    assert loaded.review_status == "approved"


@pytest.mark.integration
def test_approved_plan_consumable_by_developer_stage(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """approved-plan.json is consumable by the developer stage contract loader."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    coordinator = RunCoordinator()
    create_report = coordinator.create_issue(
        params=CreateIssueParams(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=runs_dir,
        ),
        intake=_runnable_intake(),
    )

    run_dir = Path(create_report.run_record.run_dir)
    store = RunStore(runs_dir)

    from precision_squad.models import IssueReview, IssueReviewProvenance

    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=create_report.run_record.run_id,
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            review_status="approved",
            summary="Planning may proceed.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=create_report.run_record.run_id,
                issue_ref="cracklings3d/markdown-pdf-renderer#9",
            ),
        ),
    )

    plan = ApprovedPlan(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        plan_summary="Add --version flag to CLI.",
        implementation_steps=("Implement the flag",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )
    coordinator.persist_approved_plan_for_planning(
        params=PersistApprovedPlanParams(
            run_id=create_report.run_record.run_id,
            runs_dir=runs_dir,
            approved_plan=plan,
        )
    )

    # Load via RunStore to verify consumability
    loaded = RunStore.load_approved_plan(run_dir, issue_ref="cracklings3d/markdown-pdf-renderer#9")
    assert loaded.issue_ref == "cracklings3d/markdown-pdf-renderer#9"
    assert loaded.approved is True


@pytest.mark.integration
def test_plan_review_consumable_by_implement_stage(
    make_clean_repo,
    stub_repair_adapter,
    tmp_path: Path,
) -> None:
    """plan-review.json is consumable by the implement stage."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    coordinator = RunCoordinator()
    create_report = coordinator.create_issue(
        params=CreateIssueParams(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=runs_dir,
        ),
        intake=_runnable_intake(),
    )

    run_dir = Path(create_report.run_record.run_dir)
    store = RunStore(runs_dir)

    from precision_squad.models import IssueReview, IssueReviewProvenance

    store.write_issue_review(
        run_dir,
        IssueReview(
            run_id=create_report.run_record.run_id,
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            review_status="approved",
            summary="Planning may proceed.",
            feedback=(),
            provenance=IssueReviewProvenance(
                source_artifact="issue-draft.json",
                run_id=create_report.run_record.run_id,
                issue_ref="cracklings3d/markdown-pdf-renderer#9",
            ),
        ),
    )

    plan = ApprovedPlan(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        plan_summary="Add --version flag to CLI.",
        implementation_steps=("Implement the flag",),
        named_references=(),
        retrieval_surface_summary="src/",
        approved=True,
    )
    store.write_approved_plan(run_dir, plan)

    review_plan_report = coordinator.review_plan(
        params=ReviewPlanParams(
            run_id=create_report.run_record.run_id,
            runs_dir=runs_dir,
        )
    )

    # Load via RunStore to verify consumability
    loaded = RunStore.load_plan_review(
        run_dir,
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        expected_run_id=create_report.run_record.run_id,
    )
    assert loaded.review_status == "approved"
