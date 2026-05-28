"""Workflow orchestration separate from the CLI surface."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Callable, Literal, Protocol, cast

from .executor import DocsFirstExecutor
from .governance import apply_governance, evaluate_run
from .intake import canonicalize_local_issue_ref, is_docs_remediation_issue
from .models import (
    ApprovedPlan,
    DecisionLogArtifact,
    EvaluationResult,
    ExecutionResult,
    GitHubIssue,
    GovernanceVerdict,
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
    PostPublishReviewResult,
    PublishPlan,
    PublishResult,
    QaResult,
    RepairResult,
    RunRecord,
    RunRequest,
)
from .post_publish_review import mirror_impl_review_to_post_publish
from .publishing import RequiredDecisionLogArtifactMissingError, build_publish_plan
from .repair import RepairAdapter
from .run_store import (
    ApprovedPlanNotFoundError,
    ApprovedPlanValidationError,
    IssueReviewNotFoundError,
    IssueReviewValidationError,
    PlanReviewError,
    RunStore,
)


class RepairDependencies(Protocol):
    """Dependencies that drive one repair issue workflow."""

    def create_repair_adapter(
        self, *, repair_agent: str, repair_model: str | None
    ) -> RepairAdapter | None: ...

    def run_repair_qa_loop(
        self,
        *,
        repo_path: Path,
        adapter: RepairAdapter | None,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
    ) -> tuple[RepairResult, QaResult, QaResult]: ...

    def run_docs_remediation_repair(
        self,
        *,
        repo_path: Path,
        adapter: RepairAdapter | None,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
    ) -> RepairResult: ...

    def evaluate_docs_remediation_validation(
        self,
        *,
        intake: IssueIntake,
        validation_result: ExecutionResult,
    ) -> tuple[ExecutionResult, str | None]: ...

    def merge_docs_remediation_execution_result(
        self,
        synthesis_result: ExecutionResult,
        repair_result: RepairResult,
        validation_result: ExecutionResult | None,
        validation_scope_summary: str | None = None,
    ) -> ExecutionResult: ...

    def merge_execution_result(
        self,
        synthesis_result: ExecutionResult,
        repair_result: RepairResult,
        qa_result: QaResult | None = None,
    ) -> ExecutionResult: ...

    def synthesis_artifacts_ready(self, execution_result: ExecutionResult) -> bool: ...

    def execute_publish_plan(
        self,
        intake: IssueIntake,
        plan: PublishPlan,
        *,
        publish: bool,
        run_dir: Path | None = None,
    ) -> PublishResult: ...

    def run_post_publish_review_if_needed(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        publish_result: PublishResult,
        review_model: str | None,
    ) -> ImplReviewResult | PostPublishReviewResult | None: ...

    def post_publish_review_is_stale(
        self, intake: IssueIntake, review_result: PostPublishReviewResult
    ) -> bool: ...

    def run_impl_review(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        publish_plan: PublishPlan,
        publish_result: PublishResult,
        review_model: str | None,
    ) -> ImplReviewResult: ...


class PublishDependencies(Protocol):
    """Dependencies that drive publish-run orchestration."""

    def execute_publish_plan(
        self,
        intake: IssueIntake,
        plan: PublishPlan,
        *,
        publish: bool,
        run_dir: Path | None = None,
    ) -> PublishResult: ...

    def run_post_publish_review_if_needed(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        publish_result: PublishResult,
        review_model: str | None,
    ) -> ImplReviewResult | PostPublishReviewResult | None: ...

    def post_publish_review_is_stale(
        self, intake: IssueIntake, review_result: PostPublishReviewResult
    ) -> bool: ...

    def run_impl_review(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        publish_plan: PublishPlan,
        publish_result: PublishResult,
        review_model: str | None,
    ) -> ImplReviewResult: ...


ReviewStagesOverride = Literal["plan", "all"]


@dataclass(frozen=True, slots=True)
class RepairIssueParams:
    issue_ref: str
    runs_dir: Path
    repo_path: Path
    publish: bool
    repair_agent: str
    repair_model: str | None
    review_model: str | None
    review_stages: ReviewStagesOverride | None = None
    retry_from: str | None = None
    approved_plan: ApprovedPlan | None = None


@dataclass(frozen=True, slots=True)
class PublishRunParams:
    run_id: str
    runs_dir: Path
    review_model: str | None
    publish: bool = True
    run_post_publish_review: bool = True


@dataclass(frozen=True, slots=True)
class ImplementRunParams:
    run_id: str
    runs_dir: Path
    repo_path: Path
    repair_agent: str
    repair_model: str | None


@dataclass(frozen=True, slots=True)
class RepairIssueReport:
    intake: IssueIntake
    run_record: RunRecord
    issue_review: IssueReview | None = None
    plan_review: PlanReview | None = None
    execution_result: ExecutionResult | None = None
    evaluation_result: EvaluationResult | None = None
    governance_verdict: GovernanceVerdict | None = None
    publish_plan: PublishPlan | None = None
    publish_result: PublishResult | None = None
    repair_result: RepairResult | None = None
    baseline_qa_result: QaResult | None = None
    qa_result: QaResult | None = None
    post_publish_review_result: PostPublishReviewResult | None = None
    exit_code: int = 0


@dataclass(frozen=True, slots=True)
class PublishRunReport:
    run_id: str
    run_dir: Path
    publish_plan: PublishPlan
    publish_result: PublishResult
    post_publish_review_result: PostPublishReviewResult | None


@dataclass(frozen=True, slots=True)
class ImplementRunReport:
    intake: IssueIntake
    run_record: RunRecord
    execution_result: ExecutionResult
    evaluation_result: EvaluationResult
    governance_verdict: GovernanceVerdict
    repair_result: RepairResult | None = None
    baseline_qa_result: QaResult | None = None
    qa_result: QaResult | None = None
    exit_code: int = 0


@dataclass(frozen=True, slots=True)
class CreateIssueParams:
    issue_ref: str
    runs_dir: Path


@dataclass(frozen=True, slots=True)
class CreateIssueReport:
    intake: IssueIntake
    run_record: RunRecord


@dataclass(frozen=True, slots=True)
class ReviewIssueParams:
    run_id: str
    runs_dir: Path


@dataclass(frozen=True, slots=True)
class ReviewIssueReport:
    run_record: RunRecord
    issue_review: IssueReview
    exit_code: int = 0


@dataclass(frozen=True, slots=True)
class ReviewPlanParams:
    run_id: str
    runs_dir: Path


@dataclass(frozen=True, slots=True)
class ReviewPlanReport:
    run_record: RunRecord
    plan_review: PlanReview
    exit_code: int = 0


@dataclass(frozen=True, slots=True)
class ReviewImplParams:
    run_id: str
    runs_dir: Path
    review_model: str | None


@dataclass(frozen=True, slots=True)
class ReviewImplReport:
    run_record: RunRecord
    impl_review: ImplReviewResult
    exit_code: int = 0


@dataclass(frozen=True, slots=True)
class PersistApprovedPlanParams:
    run_id: str
    runs_dir: Path
    approved_plan: ApprovedPlan


class RunCoordinator:
    """Coordinates repair and publish workflows independent of CLI output."""

    def create_issue(self, *, params: CreateIssueParams, intake: IssueIntake) -> CreateIssueReport:
        store = RunStore(params.runs_dir)
        request = RunRequest(issue_ref=params.issue_ref, runs_dir=str(params.runs_dir))
        record = store.create_run(request, intake)
        return CreateIssueReport(intake=intake, run_record=record)

    def review_issue(self, *, params: ReviewIssueParams) -> ReviewIssueReport:
        store = RunStore(params.runs_dir)
        record = store.load_run(params.run_id)
        review = _derive_issue_review(store=store, record=record)
        store.write_issue_review(Path(record.run_dir).resolve(), review)
        if review.review_status == "approved":
            exit_code = 0
        elif review.review_status == "changes_requested":
            exit_code = 2
        else:
            exit_code = 3
        return ReviewIssueReport(run_record=record, issue_review=review, exit_code=exit_code)

    def review_plan(self, *, params: ReviewPlanParams) -> ReviewPlanReport:
        store = RunStore(params.runs_dir)
        record = store.load_run(params.run_id)
        review = _derive_plan_review(store=store, record=record)
        store.write_plan_review(Path(record.run_dir).resolve(), review)
        if review.review_status == "approved":
            exit_code = 0
        elif review.review_status == "changes_requested":
            exit_code = 2
        else:
            exit_code = 3
        return ReviewPlanReport(run_record=record, plan_review=review, exit_code=exit_code)

    def review_impl(
        self,
        *,
        params: ReviewImplParams,
        dependencies: PublishDependencies,
    ) -> ReviewImplReport:
        store = RunStore(params.runs_dir)
        record = store.load_run(params.run_id)
        run_dir = Path(record.run_dir).resolve()
        intake = _load_issue_intake_artifact(run_dir, expected_issue_ref=record.issue_ref)
        RunStore.load_approved_plan(run_dir, issue_ref=record.issue_ref)
        publish_plan = _load_publish_plan_artifact(run_dir)
        publish_result = _load_publish_result_artifact(run_dir)
        impl_review = _run_impl_review_with_compatibility(
            dependencies=dependencies,
            intake=intake,
            run_record=record,
            run_dir=run_dir,
            publish_plan=publish_plan,
            publish_result=publish_result,
            review_model=params.review_model,
        )
        store.write_impl_review(run_dir, impl_review)
        store.write_post_publish_review_result(
            run_dir,
            mirror_impl_review_to_post_publish(impl_review),
        )
        if impl_review.review_status == "approved":
            exit_code = 0
        elif impl_review.review_status == "changes_requested":
            exit_code = 2
        else:
            exit_code = 3
        return ReviewImplReport(run_record=record, impl_review=impl_review, exit_code=exit_code)

    def persist_approved_plan_for_planning(self, *, params: PersistApprovedPlanParams) -> Path:
        store = RunStore(params.runs_dir)
        record = store.load_run(params.run_id)
        if not _same_local_issue_ref(record.issue_ref, params.approved_plan.issue_ref):
            raise ValueError(
                "Approved plan issue_ref does not match the stored run issue_ref "
                "for planning ingress."
            )
        run_dir = Path(record.run_dir).resolve()
        store.write_gated_approved_plan(
            run_dir,
            params.approved_plan,
            expected_run_id=record.run_id,
        )
        return run_dir / "approved-plan.json"

    def implement_run(
        self,
        *,
        params: ImplementRunParams,
        dependencies: RepairDependencies,
    ) -> ImplementRunReport:
        store = RunStore(params.runs_dir)
        record = store.load_run(params.run_id)
        run_dir = Path(record.run_dir).resolve()
        intake = _load_issue_intake_artifact(run_dir, expected_issue_ref=record.issue_ref)
        RunStore.load_approved_plan(run_dir, issue_ref=record.issue_ref)
        try:
            RunStore.require_plan_review_for_implement(run_dir, issue_ref=record.issue_ref)
        except PlanReviewError as exc:
            raise ValueError(str(exc)) from exc

        return self._run_local_implementation_flow(
            store=store,
            intake=intake,
            record=record,
            run_dir=run_dir,
            repo_path=params.repo_path,
            repair_agent=params.repair_agent,
            repair_model=params.repair_model,
            dependencies=dependencies,
        )

    def repair_issue(
        self,
        *,
        params: RepairIssueParams,
        intake: IssueIntake,
        dependencies: RepairDependencies,
    ) -> RepairIssueReport:
        store = RunStore(params.runs_dir)

        # Handle retry logic
        attempt = 1
        previous_run_dir: Path | None = None
        if params.retry_from is not None:
            try:
                previous_record = store.load_run(params.retry_from)
                if not _same_local_issue_ref(previous_record.issue_ref, params.issue_ref):
                    return _blocked_retry_report(intake=intake, issue_ref=params.issue_ref)
                attempt = previous_record.attempt + 1
                previous_run_dir = Path(previous_record.run_dir).resolve()
            except ValueError:
                return _blocked_retry_report(intake=intake, issue_ref=params.issue_ref)

        effective_approved_plan = params.approved_plan
        if effective_approved_plan is None and previous_run_dir is not None:
            try:
                effective_approved_plan = RunStore.load_approved_plan(
                    previous_run_dir,
                    issue_ref=params.issue_ref,
                )
            except ApprovedPlanNotFoundError:
                raise ValueError(
                    "Retry requires a prior approved-plan.json when "
                    "--approved-plan-path is omitted; "
                    f"missing prior approved-plan.json in {previous_run_dir}."
                )
            except ApprovedPlanValidationError as exc:
                raise ValueError(
                    "Retry carry-forward failed because the prior approved-plan.json failed "
                    f"structural validation: {exc}"
                ) from exc
            except ValueError:
                return _blocked_retry_report(intake=intake, issue_ref=params.issue_ref)

        request = RunRequest(issue_ref=params.issue_ref, runs_dir=str(params.runs_dir))

        # Check if escalated (max 3 attempts exceeded)
        if attempt > 3:
            return self._handle_escalation(
                store=store,
                request=request,
                intake=intake,
                attempt=attempt,
                effective_approved_plan=effective_approved_plan,
                dependencies=dependencies,
                params=params,
            )

        create_report = self.create_issue(
            params=CreateIssueParams(
                issue_ref=params.issue_ref,
                runs_dir=params.runs_dir,
            ),
            intake=intake,
        )
        record = create_report.run_record
        run_dir = Path(record.run_dir).resolve()

        # Update attempt counter if retrying
        if attempt > 1:
            record = record.with_attempt(attempt)
            store.write_run_record(record)

        # Handle blocked intake: apply governance and publish directly without review stages
        if intake.assessment.status == "blocked":
            verdict = apply_governance(intake, execution_result=None, evaluation_result=None)
            publish_plan = build_publish_plan(intake, record, verdict)
            store.write_governance_verdict(run_dir, verdict)
            store.write_publish_plan(run_dir, publish_plan)
            publish_result = dependencies.execute_publish_plan(
                intake,
                publish_plan,
                publish=params.publish,
            )
            store.write_publish_result(run_dir, publish_result)
            return RepairIssueReport(
                intake=intake,
                run_record=record,
                governance_verdict=verdict,
                publish_plan=publish_plan,
                publish_result=publish_result,
                exit_code=3,
            )

        issue_review_report = self.review_issue(
            params=ReviewIssueParams(
                run_id=record.run_id,
                runs_dir=params.runs_dir,
            )
        )
        if issue_review_report.exit_code != 0:
            return RepairIssueReport(
                intake=intake,
                run_record=record,
                issue_review=issue_review_report.issue_review,
                exit_code=issue_review_report.exit_code,
            )

        # Persist the approved plan only if provided
        if effective_approved_plan is not None:
            self.persist_approved_plan_for_planning(
                params=PersistApprovedPlanParams(
                    run_id=record.run_id,
                    runs_dir=params.runs_dir,
                    approved_plan=effective_approved_plan,
                )
            )
        plan_review_report = self.review_plan(
            params=ReviewPlanParams(
                run_id=record.run_id,
                runs_dir=params.runs_dir,
            )
        )
        if plan_review_report.exit_code != 0:
            return RepairIssueReport(
                intake=intake,
                run_record=record,
                issue_review=issue_review_report.issue_review,
                plan_review=plan_review_report.plan_review,
                exit_code=plan_review_report.exit_code,
            )

        implementation_report = self.implement_run(
            params=ImplementRunParams(
                run_id=record.run_id,
                runs_dir=params.runs_dir,
                repo_path=params.repo_path,
                repair_agent=params.repair_agent,
                repair_model=params.repair_model,
            ),
            dependencies=dependencies,
        )
        if implementation_report.governance_verdict.status != "approved":
            return RepairIssueReport(
                intake=intake,
                run_record=record,
                issue_review=issue_review_report.issue_review,
                plan_review=plan_review_report.plan_review,
                execution_result=implementation_report.execution_result,
                evaluation_result=implementation_report.evaluation_result,
                governance_verdict=implementation_report.governance_verdict,
                repair_result=implementation_report.repair_result,
                baseline_qa_result=implementation_report.baseline_qa_result,
                qa_result=implementation_report.qa_result,
                exit_code=implementation_report.exit_code,
            )

        try:
            publish_plan = build_publish_plan(
                intake,
                record,
                implementation_report.governance_verdict,
                implementation_report.repair_result,
            )
        except RequiredDecisionLogArtifactMissingError as exc:
            execution_result = ExecutionResult(
                status="failed_infra",
                executor_name=implementation_report.execution_result.executor_name,
                summary=str(exc),
                detail_codes=tuple(
                    dict.fromkeys(
                        (
                            *implementation_report.execution_result.detail_codes,
                            "missing_decision_log_artifact",
                        )
                    )
                ),
                artifact_dir=implementation_report.execution_result.artifact_dir,
                stdout_path=implementation_report.execution_result.stdout_path,
                stderr_path=implementation_report.execution_result.stderr_path,
                quality=implementation_report.execution_result.quality,
            )
            implementation_report = self._evaluate_and_persist_local(
                store=store,
                intake=intake,
                record=record,
                run_dir=run_dir,
                execution_result=execution_result,
                repair_result=None,
                baseline_qa_result=implementation_report.baseline_qa_result,
                qa_result=implementation_report.qa_result,
            )
            if implementation_report.governance_verdict.status != "approved":
                return RepairIssueReport(
                    intake=intake,
                    run_record=record,
                    issue_review=issue_review_report.issue_review,
                    plan_review=plan_review_report.plan_review,
                    execution_result=implementation_report.execution_result,
                    evaluation_result=implementation_report.evaluation_result,
                    governance_verdict=implementation_report.governance_verdict,
                    repair_result=implementation_report.repair_result,
                    baseline_qa_result=implementation_report.baseline_qa_result,
                    qa_result=implementation_report.qa_result,
                    exit_code=implementation_report.exit_code,
                )
            publish_plan = build_publish_plan(
                intake,
                record,
                implementation_report.governance_verdict,
                implementation_report.repair_result,
            )
        store.write_publish_plan(run_dir, publish_plan)
        publish_report = self.publish_run(
            params=PublishRunParams(
                run_id=record.run_id,
                runs_dir=params.runs_dir,
                review_model=params.review_model,
                publish=params.publish,
                run_post_publish_review=False,
            ),
            intake=intake,
            run_record=record,
            publish_plan=publish_plan,
            existing_result=None,
            existing_review_result=None,
            dependencies=dependencies,
        )

        post_publish_review_result: PostPublishReviewResult | None = None
        exit_code = implementation_report.exit_code
        if (
            publish_report.publish_result.status == "published"
            and publish_report.publish_result.target == "draft_pr"
            and publish_report.publish_result.url
        ):
            review_impl_report = self.review_impl(
                params=ReviewImplParams(
                    run_id=record.run_id,
                    runs_dir=params.runs_dir,
                    review_model=params.review_model,
                ),
                dependencies=dependencies,
            )
            post_publish_review_result = mirror_impl_review_to_post_publish(
                review_impl_report.impl_review
            )
            exit_code = review_impl_report.exit_code

        return RepairIssueReport(
            intake=intake,
            run_record=record,
            issue_review=issue_review_report.issue_review,
            plan_review=plan_review_report.plan_review,
            execution_result=implementation_report.execution_result,
            evaluation_result=implementation_report.evaluation_result,
            governance_verdict=implementation_report.governance_verdict,
            publish_plan=publish_plan,
            publish_result=publish_report.publish_result,
            repair_result=implementation_report.repair_result,
            baseline_qa_result=implementation_report.baseline_qa_result,
            qa_result=implementation_report.qa_result,
            post_publish_review_result=post_publish_review_result,
            exit_code=exit_code,
        )

    def _run_local_implementation_flow(
        self,
        *,
        store: RunStore,
        intake: IssueIntake,
        record: RunRecord,
        run_dir: Path,
        repo_path: Path,
        repair_agent: str,
        repair_model: str | None,
        dependencies: RepairDependencies,
    ) -> ImplementRunReport:
        synthesis_result = DocsFirstExecutor(repo_path=repo_path).execute(
            intake,
            record,
            run_dir,
        )
        repair_result = None
        baseline_qa_result = None
        qa_result = None
        execution_result = synthesis_result

        if is_docs_remediation_issue(intake) and dependencies.synthesis_artifacts_ready(
            synthesis_result
        ):
            execution_result, repair_result = self._run_docs_remediation_repair(
                synthesis_result=synthesis_result,
                intake=intake,
                record=record,
                run_dir=run_dir,
                repo_path=repo_path,
                repair_agent=repair_agent,
                repair_model=repair_model,
                dependencies=dependencies,
                store=store,
            )
        elif synthesis_result.status == "completed" and dependencies.synthesis_artifacts_ready(
            synthesis_result
        ):
            execution_result, repair_result, baseline_qa_result, qa_result = (
                self._run_standard_repair(
                    synthesis_result=synthesis_result,
                    intake=intake,
                    record=record,
                    run_dir=run_dir,
                    repo_path=repo_path,
                    repair_agent=repair_agent,
                    repair_model=repair_model,
                    dependencies=dependencies,
                    store=store,
                )
            )

        return self._evaluate_and_persist_local(
            store=store,
            intake=intake,
            record=record,
            run_dir=run_dir,
            execution_result=execution_result,
            repair_result=repair_result,
            baseline_qa_result=baseline_qa_result,
            qa_result=qa_result,
        )

    def _handle_escalation(
        self,
        *,
        store: RunStore,
        request: RunRequest,
        intake: IssueIntake,
        attempt: int,
        effective_approved_plan: ApprovedPlan | None,
        dependencies: RepairDependencies,
        params: RepairIssueParams,
    ) -> RepairIssueReport:
        """Handle escalation when max attempts exceeded."""
        record = store.create_run(request, intake)
        run_dir = Path(record.run_dir).resolve()
        record = record.with_attempt(attempt)
        store.write_run_record(record)
        if effective_approved_plan is not None:
            store.write_approved_plan(run_dir, effective_approved_plan)

        escalated_result = RepairResult(
            status="escalated",
            summary=f"Repair escalated after {attempt - 1} failed attempts.",
            detail_codes=("escalated_after_retries",),
        )
        store.write_repair_result(run_dir, escalated_result)

        verdict = GovernanceVerdict(
            status="blocked",
            summary=f"Repair escalated after {attempt - 1} failed attempts.",
            reason_codes=("escalated_after_retries",),
        )
        store.write_governance_verdict(run_dir, verdict)
        publish_plan = build_publish_plan(intake, record, verdict)
        store.write_publish_plan(run_dir, publish_plan)
        publish_result = dependencies.execute_publish_plan(
            intake,
            publish_plan,
            publish=params.publish,
        )
        store.write_publish_result(run_dir, publish_result)
        return RepairIssueReport(
            intake=intake,
            run_record=record,
            governance_verdict=verdict,
            publish_plan=publish_plan,
            publish_result=publish_result,
            repair_result=escalated_result,
            exit_code=4,
        )

    def _run_docs_remediation_repair(
        self,
        *,
        synthesis_result: ExecutionResult,
        intake: IssueIntake,
        record: RunRecord,
        run_dir: Path,
        repo_path: Path,
        repair_agent: str,
        repair_model: str | None,
        dependencies: RepairDependencies,
        store: RunStore,
    ) -> tuple[ExecutionResult, RepairResult]:
        """Run docs-remediation repair."""
        repair_adapter = dependencies.create_repair_adapter(
            repair_agent=repair_agent,
            repair_model=repair_model,
        )
        repair_result = dependencies.run_docs_remediation_repair(
            repo_path=repo_path,
            adapter=repair_adapter,
            intake=intake,
            run_record=record,
            run_dir=run_dir,
            contract_artifact_dir=(
                Path(synthesis_result.artifact_dir).resolve()
                if synthesis_result.artifact_dir
                else run_dir
            ),
        )
        store.write_repair_result(run_dir, repair_result)
        if repair_result.status == "completed":
            store.write_decision_log(
                run_dir,
                DecisionLogArtifact(
                    attempt=record.attempt,
                    entries=repair_result.design_decisions,
                ),
            )
        validation_result = None
        validation_scope_summary = None
        if repair_result.status == "completed" and repair_result.workspace_path:
            validation_run_dir = run_dir / "docs-remediation-validation"
            validation_repo_path = Path(repair_result.workspace_path).resolve() / "repo"
            validation_result = DocsFirstExecutor(repo_path=validation_repo_path).execute(
                intake,
                record,
                validation_run_dir,
            )
            validation_result, validation_scope_summary = (
                dependencies.evaluate_docs_remediation_validation(
                    intake=intake,
                    validation_result=validation_result,
                )
            )
        execution_result = dependencies.merge_docs_remediation_execution_result(
            synthesis_result,
            repair_result,
            validation_result,
            validation_scope_summary,
        )
        return execution_result, repair_result

    def _run_standard_repair(
        self,
        *,
        synthesis_result: ExecutionResult,
        intake: IssueIntake,
        record: RunRecord,
        run_dir: Path,
        repo_path: Path,
        repair_agent: str,
        repair_model: str | None,
        dependencies: RepairDependencies,
        store: RunStore,
    ) -> tuple[ExecutionResult, RepairResult | None, QaResult | None, QaResult | None]:
        """Run standard repair with QA loop."""
        repair_adapter = dependencies.create_repair_adapter(
            repair_agent=repair_agent,
            repair_model=repair_model,
        )
        repair_result, baseline_qa_result, qa_result = dependencies.run_repair_qa_loop(
            repo_path=repo_path,
            adapter=repair_adapter,
            intake=intake,
            run_record=record,
            run_dir=run_dir,
            contract_artifact_dir=(
                Path(synthesis_result.artifact_dir).resolve()
                if synthesis_result.artifact_dir
                else run_dir
            ),
        )
        store.write_repair_result(run_dir, repair_result)
        if repair_result.status == "completed":
            store.write_decision_log(
                run_dir,
                DecisionLogArtifact(
                    attempt=record.attempt,
                    entries=repair_result.design_decisions,
                ),
            )
        if baseline_qa_result is not None:
            store.write_qa_result(run_dir, baseline_qa_result)
        if qa_result is not None:
            store.write_qa_result(run_dir, qa_result)
        execution_result = dependencies.merge_execution_result(
            synthesis_result,
            repair_result,
            qa_result,
        )
        return execution_result, repair_result, baseline_qa_result, qa_result

    def _evaluate_and_persist_local(
        self,
        *,
        store: RunStore,
        intake: IssueIntake,
        record: RunRecord,
        run_dir: Path,
        execution_result: ExecutionResult,
        repair_result: RepairResult | None,
        baseline_qa_result: QaResult | None,
        qa_result: QaResult | None,
    ) -> ImplementRunReport:
        """Run evaluation and governance without crossing the publish boundary."""
        store.write_execution_result(run_dir, execution_result)
        evaluation_result = evaluate_run(intake, execution_result)
        store.write_evaluation_result(run_dir, evaluation_result)
        verdict = apply_governance(intake, execution_result, evaluation_result)
        store.write_governance_verdict(run_dir, verdict)

        execution_result, evaluation_result, verdict = self._ensure_decision_log_artifact(
            store=store,
            intake=intake,
            record=record,
            run_dir=run_dir,
            execution_result=execution_result,
            repair_result=repair_result,
        )

        exit_code = 0
        if verdict.status == "blocked":
            exit_code = 4

        return ImplementRunReport(
            intake=intake,
            run_record=record,
            execution_result=execution_result,
            evaluation_result=evaluation_result,
            governance_verdict=verdict,
            repair_result=repair_result,
            baseline_qa_result=baseline_qa_result,
            qa_result=qa_result,
            exit_code=exit_code,
        )

    def _publish_repair_issue_report(
        self,
        *,
        store: RunStore,
        implementation_report: ImplementRunReport,
        params: RepairIssueParams,
        dependencies: RepairDependencies,
    ) -> RepairIssueReport:
        intake = implementation_report.intake
        record = implementation_report.run_record
        run_dir = Path(record.run_dir).resolve()
        execution_result = implementation_report.execution_result
        evaluation_result = implementation_report.evaluation_result
        verdict = implementation_report.governance_verdict
        repair_result = implementation_report.repair_result
        baseline_qa_result = implementation_report.baseline_qa_result
        qa_result = implementation_report.qa_result

        publish_plan = build_publish_plan(intake, record, verdict, repair_result)
        store.write_publish_plan(run_dir, publish_plan)
        publish_result = dependencies.execute_publish_plan(
            intake,
            publish_plan,
            publish=params.publish,
            run_dir=run_dir,
        )
        store.write_publish_result(run_dir, publish_result)
        compatibility_review_result = dependencies.run_post_publish_review_if_needed(
            intake=intake,
            run_record=record,
            run_dir=run_dir,
            publish_result=publish_result,
            review_model=params.review_model,
        )
        post_publish_review_result = _persist_post_publish_compatibility_artifacts(
            store=store,
            run_dir=run_dir,
            review_result=compatibility_review_result,
        )

        return RepairIssueReport(
            intake=intake,
            run_record=record,
            execution_result=execution_result,
            evaluation_result=evaluation_result,
            governance_verdict=verdict,
            publish_plan=publish_plan,
            publish_result=publish_result,
            repair_result=repair_result,
            baseline_qa_result=baseline_qa_result,
            qa_result=qa_result,
            post_publish_review_result=post_publish_review_result,
            exit_code=implementation_report.exit_code,
        )

    def _ensure_decision_log_artifact(
        self,
        *,
        store: RunStore,
        intake: IssueIntake,
        record: RunRecord,
        run_dir: Path,
        execution_result: ExecutionResult,
        repair_result: RepairResult | None,
    ) -> tuple[ExecutionResult, EvaluationResult, GovernanceVerdict]:
        if repair_result is None or repair_result.status != "completed":
            evaluation_result = evaluate_run(intake, execution_result)
            verdict = apply_governance(intake, execution_result, evaluation_result)
            return execution_result, evaluation_result, verdict

        decision_log_path = run_dir / f"decision-log.attempt-{record.attempt}.json"
        if decision_log_path.exists():
            evaluation_result = evaluate_run(intake, execution_result)
            verdict = apply_governance(intake, execution_result, evaluation_result)
            return execution_result, evaluation_result, verdict

        execution_result = ExecutionResult(
            status="failed_infra",
            executor_name=execution_result.executor_name,
            summary=(
                "Required decision log artifact missing: "
                f"{decision_log_path.name}"
            ),
            detail_codes=tuple(
                dict.fromkeys((*execution_result.detail_codes, "missing_decision_log_artifact"))
            ),
            artifact_dir=execution_result.artifact_dir,
            stdout_path=execution_result.stdout_path,
            stderr_path=execution_result.stderr_path,
            quality=execution_result.quality,
        )
        store.write_execution_result(run_dir, execution_result)
        evaluation_result = evaluate_run(intake, execution_result)
        store.write_evaluation_result(run_dir, evaluation_result)
        verdict = apply_governance(intake, execution_result, evaluation_result)
        store.write_governance_verdict(run_dir, verdict)
        return execution_result, evaluation_result, verdict

    def _evaluate_and_publish(
        self,
        *,
        store: RunStore,
        intake: IssueIntake,
        record: RunRecord,
        run_dir: Path,
        execution_result: ExecutionResult,
        repair_result: RepairResult | None,
        baseline_qa_result: QaResult | None,
        qa_result: QaResult | None,
        params: RepairIssueParams,
        dependencies: RepairDependencies,
    ) -> RepairIssueReport:
        """Run evaluation, governance, and publish."""
        implementation_report = self._evaluate_and_persist_local(
            store=store,
            intake=intake,
            record=record,
            run_dir=run_dir,
            execution_result=execution_result,
            repair_result=repair_result,
            baseline_qa_result=baseline_qa_result,
            qa_result=qa_result,
        )
        try:
            return self._publish_repair_issue_report(
                store=store,
                implementation_report=implementation_report,
                params=params,
                dependencies=dependencies,
            )
        except RequiredDecisionLogArtifactMissingError as exc:
            execution_result = ExecutionResult(
                status="failed_infra",
                executor_name=implementation_report.execution_result.executor_name,
                summary=str(exc),
                detail_codes=tuple(
                    dict.fromkeys(
                        (
                            *implementation_report.execution_result.detail_codes,
                            "missing_decision_log_artifact",
                        )
                    )
                ),
                artifact_dir=implementation_report.execution_result.artifact_dir,
                stdout_path=implementation_report.execution_result.stdout_path,
                stderr_path=implementation_report.execution_result.stderr_path,
                quality=implementation_report.execution_result.quality,
            )
            implementation_report = self._evaluate_and_persist_local(
                store=store,
                intake=intake,
                record=record,
                run_dir=run_dir,
                execution_result=execution_result,
                repair_result=None,
                baseline_qa_result=baseline_qa_result,
                qa_result=qa_result,
            )
            return self._publish_repair_issue_report(
                store=store,
                implementation_report=implementation_report,
                params=params,
                dependencies=dependencies,
            )

    def publish_run(
        self,
        *,
        params: PublishRunParams,
        intake: IssueIntake,
        run_record: RunRecord,
        publish_plan: PublishPlan,
        existing_result: PublishResult | None,
        existing_review_result: PostPublishReviewResult | None,
        dependencies: PublishDependencies,
    ) -> PublishRunReport:
        run_dir = (params.runs_dir / params.run_id).resolve()
        if not run_dir.exists():
            raise ValueError(f"Run directory not found: {run_dir}")

        result = existing_result
        review_result = existing_review_result
        store = RunStore(params.runs_dir)

        if existing_result is not None and existing_result.status == "published":
            if not params.run_post_publish_review:
                review_result = None
            elif review_result is None or review_result.status in {
                "failed_infra",
                "not_run",
            } or dependencies.post_publish_review_is_stale(intake, review_result):
                compatibility_review_result = dependencies.run_post_publish_review_if_needed(
                    intake=intake,
                    run_record=run_record,
                    run_dir=run_dir,
                    publish_result=existing_result,
                    review_model=params.review_model,
                )
                review_result = _persist_post_publish_compatibility_artifacts(
                    store=store,
                    run_dir=run_dir,
                    review_result=compatibility_review_result,
                )
        else:
            result = dependencies.execute_publish_plan(
                intake,
                publish_plan,
                publish=params.publish,
                run_dir=run_dir,
            )
            store.write_publish_result(run_dir, result)
            if params.run_post_publish_review:
                compatibility_review_result = dependencies.run_post_publish_review_if_needed(
                    intake=intake,
                    run_record=run_record,
                    run_dir=run_dir,
                    publish_result=result,
                    review_model=params.review_model,
                )
                review_result = _persist_post_publish_compatibility_artifacts(
                    store=store,
                    run_dir=run_dir,
                    review_result=compatibility_review_result,
                )

        if result is None:
            raise ValueError(f"Run {params.run_id} is missing publish-result.json")

        return PublishRunReport(
            run_id=params.run_id,
            run_dir=run_dir,
            publish_plan=publish_plan,
            publish_result=result,
            post_publish_review_result=review_result,
        )


def _same_local_issue_ref(left: str, right: str) -> bool:
    return canonicalize_local_issue_ref(left) == canonicalize_local_issue_ref(right)


def _derive_issue_review(*, store: RunStore, record: RunRecord) -> IssueReview:
    blocked_findings: list[IssueReviewFeedback] = []
    change_findings: list[IssueReviewFeedback] = []
    try:
        draft = store.load_issue_draft(record.run_id)
    except FileNotFoundError:
        blocked_findings.append(
            _issue_review_feedback(
                code="issue_draft_missing",
                message="Create issue must persist issue-draft.json before review issue can run.",
                field="",
            )
        )
        return _issue_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )
    except (JSONDecodeError, OSError, ValueError) as exc:
        blocked_findings.append(
            _issue_review_feedback(
                code="issue_draft_unreadable",
                message=f"issue-draft.json could not be loaded for review: {exc}",
                field="",
            )
        )
        return _issue_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )

    _collect_issue_review_findings(
        draft=draft,
        record=record,
        blocked_findings=blocked_findings,
        change_findings=change_findings,
    )
    if blocked_findings:
        return _issue_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )
    if change_findings:
        return _issue_review_artifact(
            record=record,
            status="changes_requested",
            feedback=tuple(change_findings),
        )
    return _issue_review_artifact(record=record, status="approved", feedback=())


def _collect_issue_review_findings(
    *,
    draft: IssueDraft,
    record: RunRecord,
    blocked_findings: list[IssueReviewFeedback],
    change_findings: list[IssueReviewFeedback],
) -> None:
    expected_issue_ref = canonicalize_local_issue_ref(record.issue_ref)
    draft_issue_ref = canonicalize_local_issue_ref(draft.issue_ref)
    if draft_issue_ref != expected_issue_ref:
        blocked_findings.append(
            _issue_review_feedback(
                code="issue_identity_mismatch",
                message="issue-draft.json issue_ref does not match the stored run issue_ref.",
                field="issue_ref",
            )
        )
        return

    if not draft.summary.strip():
        change_findings.append(
            _issue_review_feedback(
                code="missing_summary",
                message=(
                    "issue-draft.json must include a non-empty summary before "
                    "planning can proceed."
                ),
                field="summary",
            )
        )
    if not draft.problem_statement.strip():
        change_findings.append(
            _issue_review_feedback(
                code="missing_problem_statement",
                message=(
                    "issue-draft.json must include a non-empty problem_statement "
                    "before planning can proceed."
                ),
                field="problem_statement",
            )
        )

    expected_sources = {"run-request.json", "issue-intake.json"}
    actual_sources = set(draft.provenance.source_artifacts)
    missing_sources = sorted(expected_sources - actual_sources)
    if missing_sources:
        change_findings.append(
            _issue_review_feedback(
                code="missing_issue_stage_provenance",
                message=(
                    "issue-draft.json provenance must reference run-request.json and "
                    f"issue-intake.json; missing {', '.join(missing_sources)}."
                ),
                field="provenance.source_artifacts",
            )
        )
    if canonicalize_local_issue_ref(draft.provenance.requested_issue_ref) != expected_issue_ref:
        change_findings.append(
            _issue_review_feedback(
                code="requested_issue_ref_mismatch",
                message=(
                    "issue-draft.json provenance.requested_issue_ref must match the stored run "
                    "issue_ref."
                ),
                field="provenance.requested_issue_ref",
            )
        )
    if draft.intake_status != "runnable":
        change_findings.append(
            _issue_review_feedback(
                code="intake_not_runnable",
                message=(
                    "issue-draft.json intake_status must be 'runnable' before "
                    "planning can proceed."
                ),
                field="intake_status",
            )
        )


def _issue_review_feedback(*, code: str, message: str, field: str) -> IssueReviewFeedback:
    return IssueReviewFeedback(code=code, message=message, artifact="issue-draft.json", field=field)


def _issue_review_artifact(
    *,
    record: RunRecord,
    status: str,
    feedback: tuple[IssueReviewFeedback, ...],
) -> IssueReview:
    return IssueReview(
        run_id=record.run_id,
        issue_ref=record.issue_ref,
        review_status=cast(Literal["approved", "changes_requested", "blocked"], status),
        summary=_issue_review_summary(status=status, finding_count=len(feedback)),
        feedback=feedback,
        provenance=IssueReviewProvenance(
            source_artifact="issue-draft.json",
            run_id=record.run_id,
            issue_ref=record.issue_ref,
        ),
    )


def _issue_review_summary(*, status: str, finding_count: int) -> str:
    if status == "approved":
        return (
            "Planning may proceed because issue-draft.json passed the local "
            "planner-safety review."
        )
    if status == "changes_requested":
        noun = "finding" if finding_count == 1 else "findings"
        return (
            "Planning must stop because issue-draft.json has "
            f"{finding_count} planner-safety {noun} that require changes."
        )
    noun = "finding" if finding_count == 1 else "findings"
    return (
        "Planning must stop because review issue is blocked by "
        f"{finding_count} blocking {noun} in issue-draft.json."
    )


def _derive_plan_review(*, store: RunStore, record: RunRecord) -> PlanReview:
    blocked_findings: list[PlanReviewFeedback] = []
    change_findings: list[PlanReviewFeedback] = []
    run_dir = Path(record.run_dir).resolve()
    approved_plan_path = run_dir / "approved-plan.json"

    try:
        issue_review = store.load_issue_review(
            run_dir,
            issue_ref=record.issue_ref,
            expected_run_id=record.run_id,
        )
    except IssueReviewNotFoundError:
        blocked_findings.append(
            _plan_review_feedback(
                code="issue_review_missing",
                message=(
                    "review issue must persist an approved issue-review.json before review plan "
                    "can run."
                ),
                artifact="issue-review.json",
                field="",
            )
        )
        return _plan_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )
    except IssueReviewValidationError as exc:
        blocked_findings.append(
            _plan_review_feedback(
                code="issue_review_invalid",
                message=f"issue-review.json could not be validated for plan review: {exc}",
                artifact="issue-review.json",
                field="",
            )
        )
        return _plan_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )

    if issue_review.review_status != "approved":
        blocked_findings.append(
            _plan_review_feedback(
                code="issue_review_not_approved",
                message=(
                    "review plan requires issue-review.json.review_status to be 'approved' "
                    "for the same run."
                ),
                artifact="issue-review.json",
                field="review_status",
            )
        )
        return _plan_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )

    if not approved_plan_path.exists():
        blocked_findings.append(
            _plan_review_feedback(
                code="approved_plan_missing",
                message=(
                    "plan must persist approved-plan.json for the same run before review plan "
                    "can run."
                ),
                artifact="approved-plan.json",
                field="",
            )
        )
        return _plan_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )
    try:
        with approved_plan_path.open(encoding="utf-8") as f:
            approved_plan_payload = json.load(f)
    except JSONDecodeError as exc:
        blocked_findings.append(
            _plan_review_feedback(
                code="approved_plan_invalid",
                message=(
                    "approved-plan.json could not be validated for plan review: "
                    f"invalid JSON ({exc.msg})"
                ),
                artifact="approved-plan.json",
                field="",
            )
        )
        return _plan_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )
    if not isinstance(approved_plan_payload, dict):
        blocked_findings.append(
            _plan_review_feedback(
                code="approved_plan_invalid",
                message=(
                    "approved-plan.json could not be validated for plan review: "
                    "expected a JSON object."
                ),
                artifact="approved-plan.json",
                field="",
            )
        )
        return _plan_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )

    _collect_plan_review_findings(
        approved_plan_payload=approved_plan_payload,
        record=record,
        blocked_findings=blocked_findings,
        change_findings=change_findings,
    )
    if blocked_findings:
        return _plan_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )

    try:
        store.load_approved_plan(run_dir, issue_ref=record.issue_ref)
    except ApprovedPlanNotFoundError:
        blocked_findings.append(
            _plan_review_feedback(
                code="approved_plan_missing",
                message=(
                    "plan must persist approved-plan.json for the same run before review plan "
                    "can run."
                ),
                artifact="approved-plan.json",
                field="",
            )
        )
        return _plan_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )
    except ApprovedPlanValidationError as exc:
        if not (_is_change_level_approved_plan_validation_error(exc) and change_findings):
            blocked_findings.append(
                _plan_review_feedback(
                    code="approved_plan_invalid",
                    message=f"approved-plan.json could not be validated for plan review: {exc}",
                    artifact="approved-plan.json",
                    field="",
                )
            )
            return _plan_review_artifact(
                record=record,
                status="blocked",
                feedback=tuple(blocked_findings),
            )

    if blocked_findings:
        return _plan_review_artifact(
            record=record,
            status="blocked",
            feedback=tuple(blocked_findings),
        )
    if change_findings:
        return _plan_review_artifact(
            record=record,
            status="changes_requested",
            feedback=tuple(change_findings),
        )
    return _plan_review_artifact(record=record, status="approved", feedback=())


def _collect_plan_review_findings(
    *,
    approved_plan_payload: dict[str, object],
    record: RunRecord,
    blocked_findings: list[PlanReviewFeedback],
    change_findings: list[PlanReviewFeedback],
) -> None:
    approved_plan_issue_ref = approved_plan_payload.get("issue_ref")
    if not isinstance(approved_plan_issue_ref, str) or not approved_plan_issue_ref.strip():
        blocked_findings.append(
            _plan_review_feedback(
                code="approved_plan_issue_missing",
                message=(
                    "approved-plan.json must include a non-empty issue_ref for the "
                    "reviewed run."
                ),
                artifact="approved-plan.json",
                field="issue_ref",
            )
        )
        return

    if not _same_local_issue_ref(approved_plan_issue_ref, record.issue_ref):
        blocked_findings.append(
            _plan_review_feedback(
                code="approved_plan_issue_mismatch",
                message="approved-plan.json issue_ref does not match the stored run issue_ref.",
                artifact="approved-plan.json",
                field="issue_ref",
            )
        )
        return

    plan_summary = approved_plan_payload.get("plan_summary")
    if not isinstance(plan_summary, str) or not plan_summary.strip():
        change_findings.append(
            _plan_review_feedback(
                code="missing_plan_summary",
                message=(
                    "approved-plan.json must include a non-empty plan_summary so implement "
                    "ingress receives the reviewed implementation summary explicitly."
                ),
                artifact="approved-plan.json",
                field="plan_summary",
            )
        )

    implementation_steps = approved_plan_payload.get("implementation_steps")
    if _has_correctable_implementation_steps_defect(implementation_steps):
        change_findings.append(
            _plan_review_feedback(
                code="missing_implementation_steps",
                message=(
                    "approved-plan.json must normalize to only usable implementation steps so "
                    "implement ingress does not have to reconstruct the reviewed plan."
                ),
                artifact="approved-plan.json",
                field="implementation_steps",
            )
        )

    retrieval_surface_summary = approved_plan_payload.get("retrieval_surface_summary")
    if not isinstance(retrieval_surface_summary, str) or not retrieval_surface_summary.strip():
        change_findings.append(
            _plan_review_feedback(
                code="missing_retrieval_surface_summary",
                message=(
                    "approved-plan.json must include a non-empty retrieval_surface_summary so "
                    "implement ingress does not have to guess the reviewed plan surface."
                ),
                artifact="approved-plan.json",
                field="retrieval_surface_summary",
            )
        )


def _has_usable_implementation_steps(value: object) -> bool:
    return isinstance(value, list) and any(isinstance(step, str) and step.strip() for step in value)


def _has_correctable_implementation_steps_defect(value: object) -> bool:
    if not isinstance(value, list):
        return False
    if not value:
        return True
    if not all(isinstance(step, str) for step in value):
        return False
    return any(not step.strip() for step in value) or not _has_usable_implementation_steps(value)


def _is_change_level_approved_plan_validation_error(exc: ApprovedPlanValidationError) -> bool:
    message = str(exc)
    if message in {
        "Approved plan is missing required field 'plan_summary'",
        "Approved plan is missing a non-empty 'plan_summary'",
        "Approved plan is missing required field 'implementation_steps'",
        "Approved plan has no implementation steps",
    }:
        return True
    return bool(
        re.fullmatch(
            r"Approved plan implementation_steps\[\d+\] must be a non-empty string",
            message,
        )
    )


def _plan_review_feedback(
    *,
    code: str,
    message: str,
    artifact: str,
    field: str,
) -> PlanReviewFeedback:
    return PlanReviewFeedback(code=code, message=message, artifact=artifact, field=field)


def _plan_review_artifact(
    *,
    record: RunRecord,
    status: str,
    feedback: tuple[PlanReviewFeedback, ...],
) -> PlanReview:
    return PlanReview(
        run_id=record.run_id,
        issue_ref=record.issue_ref,
        review_status=cast(Literal["approved", "changes_requested", "blocked"], status),
        summary=_plan_review_summary(status=status, finding_count=len(feedback)),
        feedback=feedback,
        provenance=PlanReviewProvenance(
            source_artifact="approved-plan.json",
            run_id=record.run_id,
            issue_ref=record.issue_ref,
        ),
    )


def _plan_review_summary(*, status: str, finding_count: int) -> str:
    if status == "approved":
        return (
            "Implementation may proceed because approved-plan.json passed the same-run "
            "plan review gate."
        )
    if status == "changes_requested":
        noun = "finding" if finding_count == 1 else "findings"
        return (
            "Implementation must stop because approved-plan.json has "
            f"{finding_count} implementation-ingress {noun} that require changes."
        )
    noun = "finding" if finding_count == 1 else "findings"
    return (
        "Implementation must stop because review plan is blocked by "
        f"{finding_count} prerequisite {noun}."
    )


def _blocked_retry_report(*, intake: IssueIntake, issue_ref: str) -> RepairIssueReport:
    return RepairIssueReport(
        intake=intake,
        run_record=RunRecord(
            run_id="",
            issue_ref=issue_ref,
            status="blocked",
            created_at="",
            updated_at="",
            run_dir="",
        ),
        exit_code=3,
    )


def _load_issue_intake_artifact(run_dir: Path, *, expected_issue_ref: str) -> IssueIntake:
    path = run_dir / "issue-intake.json"
    if not path.exists():
        raise ValueError(f"Implement ingress requires issue-intake.json at {path}.")
    try:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except JSONDecodeError as exc:
        raise ValueError(
            f"Implement ingress requires issue-intake.json at {path} to be valid JSON: {exc.msg}"
        ) from exc
    try:
        intake = _parse_issue_intake_payload(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Implement ingress requires issue-intake.json at {path} to be valid: {exc}"
        ) from exc
    if not _same_local_issue_ref(str(intake.issue.reference), expected_issue_ref):
        raise ValueError(
            "Implement ingress requires issue-intake.json to match the stored run issue_ref."
        )
    return intake


def _load_publish_plan_artifact(run_dir: Path) -> PublishPlan:
    path = run_dir / "publish-plan.json"
    if not path.exists():
        raise ValueError(f"Implementation review requires publish-plan.json at {path}.")
    try:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except JSONDecodeError as exc:
        raise ValueError(
            "Implementation review requires publish-plan.json at "
            f"{path} to be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            "Implementation review requires publish-plan.json at "
            f"{path} to be a JSON object."
        )
    status = payload.get("status")
    title = payload.get("title")
    body = payload.get("body")
    reason_codes = payload.get("reason_codes")
    if status not in {"draft_pr", "issue_comment", "follow_up_issue"}:
        raise ValueError("Implementation review requires publish-plan.json.status to be valid.")
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("Implementation review requires publish-plan.json title/body strings.")
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) for item in reason_codes
    ):
        raise ValueError(
            "Implementation review requires publish-plan.json.reason_codes "
            "to be a list of strings."
        )
    return PublishPlan(
        status=cast(Literal["draft_pr", "issue_comment", "follow_up_issue"], status),
        title=title,
        body=body,
        reason_codes=tuple(reason_codes),
        branch_name=cast(str | None, payload.get("branch_name")),
        pull_request_url=cast(str | None, payload.get("pull_request_url")),
        pull_number=cast(int | None, payload.get("pull_number")),
    )


def _load_publish_result_artifact(run_dir: Path) -> PublishResult:
    path = run_dir / "publish-result.json"
    if not path.exists():
        raise ValueError(f"Implementation review requires publish-result.json at {path}.")
    try:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except JSONDecodeError as exc:
        raise ValueError(
            "Implementation review requires publish-result.json at "
            f"{path} to be valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"Implementation review requires publish-result.json at {path} to be a JSON object."
        )
    status = payload.get("status")
    target = payload.get("target")
    summary = payload.get("summary")
    if status not in {"dry_run", "published"}:
        raise ValueError("Implementation review requires publish-result.json.status to be valid.")
    if target not in {"draft_pr", "issue_comment", "follow_up_issue"}:
        raise ValueError("Implementation review requires publish-result.json.target to be valid.")
    if not isinstance(summary, str):
        raise ValueError(
            "Implementation review requires publish-result.json.summary to be a string."
        )
    return PublishResult(
        status=cast(Literal["dry_run", "published"], status),
        target=cast(Literal["draft_pr", "issue_comment", "follow_up_issue"], target),
        summary=summary,
        url=cast(str | None, payload.get("url")),
        branch_name=cast(str | None, payload.get("branch_name")),
        pull_number=cast(int | None, payload.get("pull_number")),
    )


def _persist_post_publish_compatibility_artifacts(
    *,
    store: RunStore,
    run_dir: Path,
    review_result: ImplReviewResult | PostPublishReviewResult | None,
) -> PostPublishReviewResult | None:
    if review_result is None:
        return None
    if isinstance(review_result, ImplReviewResult):
        impl_review = review_result
        legacy_review = mirror_impl_review_to_post_publish(review_result)
    else:
        legacy_review = review_result
        impl_review = _map_legacy_post_publish_review(review_result)
    store.write_impl_review(run_dir, impl_review)
    store.write_post_publish_review_result(run_dir, legacy_review)
    return legacy_review


def _run_impl_review_with_compatibility(
    *,
    dependencies: PublishDependencies,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    publish_plan: PublishPlan,
    publish_result: PublishResult,
    review_model: str | None,
) -> ImplReviewResult:
    run_impl_review = cast(
        Callable[..., ImplReviewResult] | None,
        getattr(dependencies, "run_impl_review", None),
    )
    if callable(run_impl_review):
        return run_impl_review(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            publish_plan=publish_plan,
            publish_result=publish_result,
            review_model=review_model,
        )

    compatibility_review = dependencies.run_post_publish_review_if_needed(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        publish_result=publish_result,
        review_model=review_model,
    )
    if compatibility_review is None:
        raise ValueError(
            "Implementation review requires a dependency that provides run_impl_review() "
            "or returns a compatibility review result from run_post_publish_review_if_needed()."
        )
    if isinstance(compatibility_review, ImplReviewResult):
        return compatibility_review
    return _map_legacy_post_publish_review(compatibility_review)


def _map_legacy_post_publish_review(review: PostPublishReviewResult) -> ImplReviewResult:
    from .post_publish_review import _map_post_publish_to_impl_review

    return _map_post_publish_to_impl_review(review)


def _parse_issue_intake_payload(payload: object) -> IssueIntake:
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object")
    issue_payload = cast(dict[str, object], payload["issue"])
    reference_payload = cast(dict[str, object], issue_payload["reference"])
    assessment_payload = cast(dict[str, object], payload["assessment"])
    status = assessment_payload["status"]
    number_value = reference_payload["number"]
    if status not in {"runnable", "blocked"}:
        raise ValueError("Issue intake assessment.status must be 'runnable' or 'blocked'")
    if not isinstance(number_value, int):
        raise ValueError("Issue intake issue.reference.number must be an integer")
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference(
                owner=str(reference_payload["owner"]),
                repo=str(reference_payload["repo"]),
                number=number_value,
            ),
            title=str(issue_payload["title"]),
            body=str(issue_payload["body"]),
            labels=tuple(str(label) for label in cast(list[object], issue_payload["labels"])),
            html_url=str(issue_payload["html_url"]),
            comments=tuple(
                str(comment) for comment in cast(list[object], issue_payload.get("comments", []))
            ),
        ),
        summary=str(payload["summary"]),
        problem_statement=str(payload["problem_statement"]),
        assessment=IssueAssessment(
            status=cast(Literal["runnable", "blocked"], status),
            reason_codes=tuple(
                str(reason_code)
                for reason_code in cast(list[object], assessment_payload["reason_codes"])
            ),
        ),
    )
