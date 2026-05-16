"""Repair orchestration and result projection helpers."""

from __future__ import annotations

import shutil
import inspect
import subprocess
from pathlib import Path

from ..docs_remediation import (
    evaluate_docs_remediation_scope,
    load_contract_findings,
    summarize_docs_findings,
)
from ..github_client import GitHubClientError, GitHubWriteClient
from ..models import ExecutionResult, IssueIntake, QaResult, RepairResult, RunRecord
from ..rerun_context import latest_rejected_pull_request
from ..run_store import ApprovedPlanError, RunStore
from .adapter import RepairAdapter
from .qa import (
    WorkspaceQaVerifier,
    _failure_signature,
    _finalize_qa_result,
    _run_baseline_qa,
    build_qa_feedback,
)

DOCS_REPAIR_EXECUTOR = "docs+repair"


class RepairStage:
    """Prepares a clean workspace and delegates repair to an adapter."""

    def __init__(
        self,
        *,
        repo_path: Path,
        adapter: RepairAdapter | None,
        rerun_branch: str | None = None,
        rerun_remote_url: str | None = None,
    ) -> None:
        self.repo_path = repo_path
        self.adapter = adapter
        self.rerun_branch = rerun_branch
        self.rerun_remote_url = rerun_remote_url

    def execute(
        self,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
    ) -> RepairResult:
        run_dir = run_dir.resolve()
        contract_artifact_dir = contract_artifact_dir.resolve()

        try:
            approved_plan = RunStore.load_approved_plan(run_dir, issue_ref=run_record.issue_ref)
        except ApprovedPlanError as exc:
            return RepairResult(
                status="failed_infra",
                summary=f"Repair stage could not load the persisted approved plan: {exc}",
                detail_codes=("repair_approved_plan_invalid",),
            )

        if self.adapter is None:
            return RepairResult(
                status="not_configured",
                summary=(
                    "A documented local execution contract was prepared, but no "
                    "repair agent was configured."
                ),
                detail_codes=("repair_stage_not_configured",),
            )

        if not contract_artifact_dir.exists():
            return RepairResult(
                status="failed_infra",
                summary=(
                    "Repair stage could not find the execution contract artifacts: "
                    f"{contract_artifact_dir}"
                ),
                detail_codes=("repair_artifact_dir_missing",),
            )

        workspace_path = (run_dir / "repair-workspace").resolve()
        repo_workspace = (workspace_path / "repo").resolve()
        workspace_path.mkdir(parents=True, exist_ok=True)
        if repo_workspace.exists():
            shutil.rmtree(repo_workspace)

        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
        )
        if head_result.returncode != 0:
            return RepairResult(
                status="failed_infra",
                summary="Repair stage could not resolve the source repository HEAD commit.",
                detail_codes=("repair_repo_head_unavailable",),
                workspace_path=str(workspace_path),
            )
        base_commit = head_result.stdout.strip()

        clone_result = subprocess.run(
            ["git", "clone", "--no-hardlinks", str(self.repo_path.resolve()), str(repo_workspace)],
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
        )
        if clone_result.returncode != 0:
            return RepairResult(
                status="failed_infra",
                summary="Repair stage could not clone the source repository into a worktree.",
                detail_codes=("repair_clone_failed",),
                workspace_path=str(workspace_path),
            )

        reset_result = subprocess.run(
            ["git", "reset", "--hard", base_commit],
            cwd=str(repo_workspace),
            capture_output=True,
            text=True,
        )
        if reset_result.returncode != 0:
            return RepairResult(
                status="failed_infra",
                summary="Repair stage could not reset the worktree to the captured base commit.",
                detail_codes=("repair_reset_failed",),
                workspace_path=str(workspace_path),
            )

        rerun_reset_error = _reset_workspace_to_rerun_branch(
            repo_workspace,
            branch_name=self.rerun_branch,
            remote_url=self.rerun_remote_url,
        )
        if rerun_reset_error is not None:
            return RepairResult(
                status="failed_infra",
                summary=rerun_reset_error,
                detail_codes=("repair_rerun_branch_unavailable",),
                workspace_path=str(workspace_path),
            )

        repair_kwargs = {
            "approved_plan": approved_plan,
            "intake": intake,
            "run_record": run_record,
            "run_dir": run_dir,
            "contract_artifact_dir": contract_artifact_dir,
            "repo_workspace": repo_workspace,
        }
        parameters = inspect.signature(self.adapter.repair).parameters
        if "approved_plan" not in parameters:
            repair_kwargs.pop("approved_plan")
        return self.adapter.repair(**repair_kwargs)


def run_repair_qa_loop(
    *,
    repo_path: Path,
    adapter: RepairAdapter | None,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    contract_artifact_dir: Path,
    max_iterations: int = 2,
) -> tuple[RepairResult, QaResult, QaResult]:
    """Run bounded repair attempts with deterministic QA between iterations."""
    verifier = WorkspaceQaVerifier()
    rerun_branch = _resolve_rerun_branch(intake)
    rerun_remote_url = _resolve_remote_origin_url(repo_path) if rerun_branch else None
    qa_result = QaResult(
        status="not_run",
        summary="QA did not run.",
        detail_codes=("qa_not_run",),
    )
    last_repair_result = RepairResult(
        status="not_configured",
        summary="Repair stage did not run.",
        detail_codes=("repair_not_run",),
    )
    qa_feedback: str | None = None
    baseline_result = _run_baseline_qa(
        repo_path=repo_path,
        run_dir=run_dir,
        contract_artifact_dir=contract_artifact_dir,
        verifier=verifier,
        rerun_branch=rerun_branch,
        rerun_remote_url=rerun_remote_url,
    )
    baseline_failure_signature = (
        _failure_signature(baseline_result)
        if baseline_result.status in {"failed", "failed_infra"}
        else frozenset()
    )

    for iteration in range(1, max_iterations + 1):
        iteration_adapter = None
        if adapter is not None:
            iteration_adapter = adapter.with_qa_feedback(qa_feedback) if qa_feedback else adapter
        last_repair_result = RepairStage(
            repo_path=repo_path,
            adapter=iteration_adapter,
            rerun_branch=rerun_branch,
            rerun_remote_url=rerun_remote_url,
        ).execute(
            intake,
            run_record,
            run_dir,
            contract_artifact_dir,
        )

        if last_repair_result.status != "completed":
            return last_repair_result, baseline_result, qa_result

        workspace_path = Path(last_repair_result.workspace_path or "")
        repo_workspace = workspace_path / "repo"
        qa_result = verifier.verify(
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
            repo_workspace=repo_workspace,
            iteration=iteration,
        )
        qa_result = _finalize_qa_result(
            qa_result=qa_result,
            baseline_result=baseline_result,
            baseline_failure_signature=baseline_failure_signature,
        )
        if qa_result.status == "passed":
            return last_repair_result, baseline_result, qa_result

        if qa_result.status != "failed":
            return last_repair_result, baseline_result, qa_result

        qa_feedback = build_qa_feedback(qa_result)

    return last_repair_result, baseline_result, qa_result


def synthesis_artifacts_ready(execution_result: ExecutionResult) -> bool:
    """Return whether the execution contract artifacts needed for repair exist."""
    artifact_dir = resolve_artifact_dir(execution_result.artifact_dir)
    if artifact_dir is None:
        return False
    return (artifact_dir / "contract.json").exists()


def resolve_artifact_dir(path_str: str | None) -> Path | None:
    """Resolve a persisted artifact path into an absolute local path."""
    if path_str is None:
        return None
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def merge_execution_result(
    synthesis_result: ExecutionResult,
    repair_result: RepairResult,
    qa_result: QaResult | None = None,
) -> ExecutionResult:
    """Project synthesis and repair outcomes back into the primary execution result."""
    qa_codes = qa_result.detail_codes if qa_result is not None else ()
    detail_codes = tuple(
        dict.fromkeys((*synthesis_result.detail_codes, *repair_result.detail_codes, *qa_codes))
    )

    if (
        repair_result.status == "completed"
        and qa_result is not None
        and qa_result.status == "passed"
    ):
        return ExecutionResult(
            status="completed",
            executor_name=DOCS_REPAIR_EXECUTOR,
            summary=(
                "Documented local setup/test instructions were extracted, the repair "
                "stage produced source changes, and QA passed."
            ),
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
            quality=qa_result.quality if qa_result is not None else None,
        )

    if qa_result is not None and qa_result.status in {"failed", "unrunnable", "failed_infra"}:
        if qa_result.quality == "improved":
            return ExecutionResult(
                status="completed",
                executor_name=DOCS_REPAIR_EXECUTOR,
                summary=qa_result.summary,
                detail_codes=detail_codes,
                artifact_dir=synthesis_result.artifact_dir,
                stdout_path=synthesis_result.stdout_path,
                stderr_path=synthesis_result.stderr_path,
                quality=qa_result.quality if qa_result is not None else None,
            )
        status = "blocked" if qa_result.status in {"failed", "unrunnable"} else "failed_infra"
        return ExecutionResult(
            status=status,
            executor_name=DOCS_REPAIR_EXECUTOR,
            summary=qa_result.summary,
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
            quality=qa_result.quality if qa_result is not None else None,
        )

    if repair_result.status == "failed_infra":
        return ExecutionResult(
            status="failed_infra",
            executor_name=DOCS_REPAIR_EXECUTOR,
            summary=repair_result.summary,
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
        )

    return ExecutionResult(
        status="blocked",
        executor_name=DOCS_REPAIR_EXECUTOR,
        summary=repair_result.summary,
        detail_codes=detail_codes,
        artifact_dir=synthesis_result.artifact_dir,
        stdout_path=synthesis_result.stdout_path,
        stderr_path=synthesis_result.stderr_path,
    )


def merge_docs_remediation_execution_result(
    synthesis_result: ExecutionResult,
    repair_result: RepairResult,
    validation_result: ExecutionResult | None,
    validation_scope_summary: str | None = None,
) -> ExecutionResult:
    """Project a docs-remediation repair attempt back into the execution result."""
    detail_codes = tuple(
        dict.fromkeys(
            (
                *synthesis_result.detail_codes,
                *repair_result.detail_codes,
                *(validation_result.detail_codes if validation_result is not None else ()),
                "docs_remediation_issue",
            )
        )
    )

    if repair_result.status == "completed" and validation_result is not None:
        if validation_result.status == "completed":
            return ExecutionResult(
                status="completed",
                executor_name=DOCS_REPAIR_EXECUTOR,
                summary=(
                    validation_scope_summary
                    or (
                        "Repository documentation blockers were identified, the "
                        "docs-remediation repair stage produced focused documentation "
                        "changes, and the repaired workspace now satisfies the same "
                        "docs gate."
                    )
                ),
                detail_codes=detail_codes,
                artifact_dir=validation_result.artifact_dir,
                stdout_path=validation_result.stdout_path,
                stderr_path=validation_result.stderr_path,
            )

        return ExecutionResult(
            status=validation_result.status,
            executor_name=DOCS_REPAIR_EXECUTOR,
            summary=validation_scope_summary or validation_result.summary,
            detail_codes=detail_codes,
            artifact_dir=validation_result.artifact_dir,
            stdout_path=validation_result.stdout_path,
            stderr_path=validation_result.stderr_path,
        )

    if repair_result.status == "completed":
        return ExecutionResult(
            status="failed_infra",
            executor_name=DOCS_REPAIR_EXECUTOR,
            summary=(
                "Docs-remediation repair completed, but the repaired workspace was "
                "not revalidated."
            ),
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
        )

    if repair_result.status == "failed_infra":
        return ExecutionResult(
            status="failed_infra",
            executor_name=DOCS_REPAIR_EXECUTOR,
            summary=repair_result.summary,
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
        )

    return ExecutionResult(
        status="blocked",
        executor_name=DOCS_REPAIR_EXECUTOR,
        summary=repair_result.summary,
        detail_codes=detail_codes,
        artifact_dir=synthesis_result.artifact_dir,
        stdout_path=synthesis_result.stdout_path,
        stderr_path=synthesis_result.stderr_path,
    )


def run_docs_remediation_repair(
    *,
    repo_path: Path,
    adapter: RepairAdapter | None,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    contract_artifact_dir: Path,
) -> RepairResult:
    """Run one repair attempt for a docs-remediation issue without QA."""
    rerun_branch = _resolve_rerun_branch(intake)
    rerun_remote_url = _resolve_remote_origin_url(repo_path) if rerun_branch else None
    return RepairStage(
        repo_path=repo_path,
        adapter=adapter,
        rerun_branch=rerun_branch,
        rerun_remote_url=rerun_remote_url,
    ).execute(
        intake,
        run_record,
        run_dir,
        contract_artifact_dir,
    )


def evaluate_docs_remediation_validation(
    *,
    intake: IssueIntake,
    validation_result: ExecutionResult,
) -> tuple[ExecutionResult, str | None]:
    """Evaluate docs-remediation validation against target and baseline finding sets."""
    findings = load_contract_findings(validation_result.artifact_dir)
    scope = evaluate_docs_remediation_scope(intake.issue.body, findings)

    if scope.unresolved_target_findings:
        unresolved_summary = summarize_docs_findings(scope.unresolved_target_findings)
        summary = (
            "The docs-remediation issue is still blocked because one or more target "
            f"findings remain. Remaining target findings: {unresolved_summary}"
        )
        return (
            ExecutionResult(
                status=validation_result.status,
                executor_name=validation_result.executor_name,
                summary=summary,
                detail_codes=validation_result.detail_codes,
                artifact_dir=validation_result.artifact_dir,
                stdout_path=validation_result.stdout_path,
                stderr_path=validation_result.stderr_path,
            ),
            summary,
        )

    baseline_summary = None
    if scope.baseline_remaining_findings:
        baseline_summary = summarize_docs_findings(scope.baseline_remaining_findings)

    if scope.new_findings:
        new_summary = summarize_docs_findings(scope.new_findings)
        summary = (
            "The docs-remediation issue cleared its target findings, but new "
            f"untracked docs blockers were introduced or surfaced: {new_summary}"
        )
        return (
            ExecutionResult(
                status="missing_docs",
                executor_name=validation_result.executor_name,
                summary=summary,
                detail_codes=validation_result.detail_codes,
                artifact_dir=validation_result.artifact_dir,
                stdout_path=validation_result.stdout_path,
                stderr_path=validation_result.stderr_path,
            ),
            summary,
        )

    if baseline_summary:
        summary = (
            "The docs-remediation issue cleared all target findings. Remaining docs "
            f"blockers are baseline findings already tracked elsewhere: {baseline_summary}"
        )
    else:
        summary = (
            "The docs-remediation issue cleared all tracked target findings and did "
            "not surface any new docs blockers."
        )

    return (
        ExecutionResult(
            status="completed",
            executor_name=validation_result.executor_name,
            summary=summary,
            detail_codes=validation_result.detail_codes,
            artifact_dir=validation_result.artifact_dir,
            stdout_path=validation_result.stdout_path,
            stderr_path=validation_result.stderr_path,
        ),
        summary,
    )


def _resolve_rerun_branch(intake: IssueIntake, token_env: str = "GITHUB_TOKEN") -> str | None:
    rejected_pr = latest_rejected_pull_request(intake.issue.comments)
    if rejected_pr is None:
        return None
    try:
        client = GitHubWriteClient.from_env(token_env)
        return client.get_pull_request_head_branch(
            intake.issue.reference.owner,
            intake.issue.reference.repo,
            rejected_pr.number,
        )
    except GitHubClientError:
        return None


def _resolve_remote_origin_url(repo_path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    url = completed.stdout.strip()
    return url or None


def _reset_workspace_to_rerun_branch(
    repo_workspace: Path,
    *,
    branch_name: str | None,
    remote_url: str | None,
) -> str | None:
    if branch_name is None or remote_url is None:
        return None

    fetch_result = subprocess.run(
        ["git", "fetch", remote_url, branch_name],
        cwd=str(repo_workspace),
        capture_output=True,
        text=True,
    )
    if fetch_result.returncode != 0:
        return (
            "Repair rerun could not fetch the previous rejected pull request branch "
            f"`{branch_name}` from `{remote_url}`."
        )

    checkout_result = subprocess.run(
        ["git", "checkout", "-B", branch_name, "FETCH_HEAD"],
        cwd=str(repo_workspace),
        capture_output=True,
        text=True,
    )
    if checkout_result.returncode != 0:
        return (
            "Repair rerun could not reset the workspace to the previous rejected "
            f"pull request branch `{branch_name}`."
        )
    return None
