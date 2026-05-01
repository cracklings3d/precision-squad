"""Workflow orchestration separate from the CLI surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .executor import DocsFirstExecutor
from .governance import apply_governance, evaluate_run
from .intake import IssueIntake, is_docs_remediation_issue
from .models import (
    EvaluationResult,
    ExecutionResult,
    GovernanceVerdict,
    PostPublishReviewResult,
    PublishPlan,
    PublishResult,
    QaResult,
    RepairResult,
    RunRecord,
    RunRequest,
)
from .publishing import build_publish_plan
from .repair import RepairAdapter
from .run_store import RunStore


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
    ) -> PostPublishReviewResult | None: ...


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
    ) -> PostPublishReviewResult | None: ...

    def post_publish_review_is_stale(
        self, intake: IssueIntake, review_result: PostPublishReviewResult
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class RepairIssueParams:
    issue_ref: str
    runs_dir: Path
    repo_path: Path
    publish: bool
    repair_agent: str
    repair_model: str | None
    review_model: str | None
    retry_from: str | None = None


@dataclass(frozen=True, slots=True)
class PublishRunParams:
    run_id: str
    runs_dir: Path
    review_model: str | None


@dataclass(frozen=True, slots=True)
class RepairIssueReport:
    intake: IssueIntake
    run_record: RunRecord
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


class RunCoordinator:
    """Coordinates repair and publish workflows independent of CLI output."""

    def repair_issue(
        self,
        *,
        params: RepairIssueParams,
        intake: IssueIntake,
        dependencies: RepairDependencies,
    ) -> RepairIssueReport:
        store = RunStore(params.runs_dir)
        request = RunRequest(issue_ref=params.issue_ref, runs_dir=str(params.runs_dir))

        # Handle retry logic
        attempt = 1
        if params.retry_from is not None:
            try:
                previous_record = store.load_run(params.retry_from)
                attempt = previous_record.attempt + 1
            except ValueError:
                return RepairIssueReport(
                    intake=intake,
                    run_record=RunRecord(
                        run_id="",
                        issue_ref=params.issue_ref,
                        status="blocked",
                        created_at="",
                        updated_at="",
                        run_dir="",
                    ),
                    exit_code=3,
                )

        # Check if escalated (max 3 attempts exceeded)
        if attempt > 3:
            return self._handle_escalation(
                store=store,
                request=request,
                intake=intake,
                attempt=attempt,
                dependencies=dependencies,
                params=params,
            )

        record = store.create_run(request, intake)
        run_dir = Path(record.run_dir).resolve()

        # Update attempt counter if retrying
        if attempt > 1:
            record = record.with_attempt(attempt)
            store.write_run_record(record)

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

        synthesis_result = DocsFirstExecutor(repo_path=params.repo_path).execute(
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
                params=params,
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
                    params=params,
                    dependencies=dependencies,
                    store=store,
                )
            )

        return self._evaluate_and_publish(
            store=store,
            intake=intake,
            record=record,
            run_dir=run_dir,
            execution_result=execution_result,
            repair_result=repair_result,
            baseline_qa_result=baseline_qa_result,
            qa_result=qa_result,
            params=params,
            dependencies=dependencies,
        )

    def _handle_escalation(
        self,
        *,
        store: RunStore,
        request: RunRequest,
        intake: IssueIntake,
        attempt: int,
        dependencies: RepairDependencies,
        params: RepairIssueParams,
    ) -> RepairIssueReport:
        """Handle escalation when max attempts exceeded."""
        record = store.create_run(request, intake)
        run_dir = Path(record.run_dir).resolve()
        record = record.with_attempt(attempt)
        store.write_run_record(record)

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
        params: RepairIssueParams,
        dependencies: RepairDependencies,
        store: RunStore,
    ) -> tuple[ExecutionResult, RepairResult]:
        """Run docs-remediation repair."""
        repair_adapter = dependencies.create_repair_adapter(
            repair_agent=params.repair_agent,
            repair_model=params.repair_model,
        )
        repair_result = dependencies.run_docs_remediation_repair(
            repo_path=params.repo_path,
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
        params: RepairIssueParams,
        dependencies: RepairDependencies,
        store: RunStore,
    ) -> tuple[ExecutionResult, RepairResult | None, QaResult | None, QaResult | None]:
        """Run standard repair with QA loop."""
        repair_adapter = dependencies.create_repair_adapter(
            repair_agent=params.repair_agent,
            repair_model=params.repair_model,
        )
        repair_result, baseline_qa_result, qa_result = dependencies.run_repair_qa_loop(
            repo_path=params.repo_path,
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
        store.write_execution_result(run_dir, execution_result)
        evaluation_result = evaluate_run(intake, execution_result)
        store.write_evaluation_result(run_dir, evaluation_result)
        verdict = apply_governance(intake, execution_result, evaluation_result)
        store.write_governance_verdict(run_dir, verdict)
        publish_plan = build_publish_plan(intake, record, verdict, repair_result)
        store.write_publish_plan(run_dir, publish_plan)
        publish_result = dependencies.execute_publish_plan(
            intake,
            publish_plan,
            publish=params.publish,
            run_dir=run_dir,
        )
        store.write_publish_result(run_dir, publish_result)
        post_publish_review_result = dependencies.run_post_publish_review_if_needed(
            intake=intake,
            run_record=record,
            run_dir=run_dir,
            publish_result=publish_result,
            review_model=params.review_model,
        )
        if post_publish_review_result is not None:
            store.write_post_publish_review_result(run_dir, post_publish_review_result)

        exit_code = 0
        if verdict.status == "blocked":
            exit_code = 4

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
            exit_code=exit_code,
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
            if review_result is None or review_result.status in {
                "failed_infra",
                "not_run",
            } or dependencies.post_publish_review_is_stale(intake, review_result):
                review_result = dependencies.run_post_publish_review_if_needed(
                    intake=intake,
                    run_record=run_record,
                    run_dir=run_dir,
                    publish_result=existing_result,
                    review_model=params.review_model,
                )
                if review_result is not None:
                    store.write_post_publish_review_result(run_dir, review_result)
        else:
            result = dependencies.execute_publish_plan(
                intake,
                publish_plan,
                publish=True,
                run_dir=run_dir,
            )
            store.write_publish_result(run_dir, result)
            review_result = dependencies.run_post_publish_review_if_needed(
                intake=intake,
                run_record=run_record,
                run_dir=run_dir,
                publish_result=result,
                review_model=params.review_model,
            )
            if review_result is not None:
                store.write_post_publish_review_result(run_dir, review_result)

        if result is None:
            raise ValueError(f"Run {params.run_id} is missing publish-result.json")

        return PublishRunReport(
            run_id=params.run_id,
            run_dir=run_dir,
            publish_plan=publish_plan,
            publish_result=result,
            post_publish_review_result=review_result,
        )
