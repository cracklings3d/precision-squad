"""Shared helpers for integration pipeline tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from precision_squad.models import (
    ApprovedPlan,
    ImplReviewResult,
    IssueIntake,
    PublishResult,
    QaResult,
    RepairResult,
    RunRecord,
)
from precision_squad.repair import RepairAdapter


def approved_plan_for(issue_ref: str = "cracklings3d/markdown-pdf-renderer#9") -> ApprovedPlan:
    """Return a minimal approved plan fixture for integration runs."""

    return ApprovedPlan(
        issue_ref=issue_ref,
        plan_summary="Repair the issue with a minimal bounded change.",
        implementation_steps=("Apply the smallest coherent fix.",),
        named_references=(),
        retrieval_surface_summary="src/ tests/",
        approved=True,
    )


def configure_git_identity(repo_workspace: Path) -> None:
    """Configure a local git identity for test commits."""

    for key, value in (("user.email", "test@test.local"), ("user.name", "Test")):
        subprocess.run(
            ["git", "config", key, value],
            cwd=repo_workspace,
            check=True,
            capture_output=True,
        )


class _ApprovedTestDependencies:
    """Dependency wiring for the approved pipeline path."""

    def __init__(self, adapter: RepairAdapter) -> None:
        self._adapter = adapter

    def create_repair_adapter(
        self, *, repair_agent: str, repair_model: str | None
    ) -> RepairAdapter | None:
        del repair_model
        if repair_agent == "none":
            return None
        return self._adapter

    def run_repair_qa_loop(
        self,
        *,
        repo_path: Path,
        adapter: RepairAdapter | None,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
    ) -> tuple[RepairResult, QaResult, QaResult]:
        from precision_squad.repair.orchestration import (
            RepairStage,
            _failure_signature,
            _finalize_qa_result,
            _run_baseline_qa,
        )
        from precision_squad.repair.qa import WorkspaceQaVerifier

        verifier = WorkspaceQaVerifier()
        qa_result = _run_baseline_qa(
            repo_path=repo_path,
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
            verifier=verifier,
        )
        baseline_result = qa_result
        baseline_failure_signature = (
            _failure_signature(baseline_result)
            if baseline_result.status in {"failed", "failed_infra"}
            else frozenset()
        )

        repair_result = RepairStage(
            repo_path=repo_path,
            adapter=adapter,
        ).execute(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
        )

        if repair_result.status != "completed":
            return repair_result, baseline_result, qa_result

        workspace_path = Path(repair_result.workspace_path or "")
        repo_workspace = workspace_path / "repo"
        final_qa = verifier.verify(
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
            repo_workspace=repo_workspace,
            iteration=1,
        )
        qa_result = _finalize_qa_result(
            qa_result=final_qa,
            baseline_result=baseline_result,
            baseline_failure_signature=baseline_failure_signature,
        )

        return repair_result, baseline_result, qa_result

    def run_docs_remediation_repair(self, **kwargs):
        del kwargs
        raise AssertionError("docs remediation should not run for non-docs-remediation issue")

    def evaluate_docs_remediation_validation(self, **kwargs):
        del kwargs
        raise AssertionError("validation should not run for non-docs-remediation issue")

    def merge_docs_remediation_execution_result(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("docs remediation merge should not run")

    def merge_execution_result(self, synthesis_result, repair_result, qa_result=None):
        from precision_squad.repair.orchestration import merge_execution_result as _real

        return _real(synthesis_result, repair_result, qa_result)

    def synthesis_artifacts_ready(self, execution_result):
        from precision_squad.repair.orchestration import synthesis_artifacts_ready as _real

        return _real(execution_result)

    def execute_publish_plan(self, intake, plan, *, publish, run_dir=None) -> PublishResult:
        del intake, publish, run_dir
        return PublishResult(
            status="dry_run",
            target=plan.status,
            summary="dry_run (integration test)",
            url=None,
        )

    def run_post_publish_review_if_needed(self, **kwargs):
        del kwargs
        return None

    def post_publish_review_is_stale(self, intake, review_result) -> bool:
        del intake, review_result
        return False

    def run_impl_review(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        publish_plan,
        publish_result: PublishResult,
        review_model: str | None,
    ) -> ImplReviewResult:
        del intake, run_record, run_dir, publish_plan, review_model
        return ImplReviewResult(
            verdict="approved",
            summary="Implementation review approved in integration test.",
            pull_request_url=publish_result.url,
            pull_number=publish_result.pull_number,
            pull_head_sha="integration-test-head-sha",
            reviewer_status="approved",
            reviewer_summary="Reviewer approved in integration test.",
            architect_status="approved",
            architect_summary="Architect approved in integration test.",
        )
