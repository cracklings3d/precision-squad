"""Agent-backed repair stage using a documented local execution contract."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .docs_remediation import (
    evaluate_docs_remediation_scope,
    extract_docs_target_findings,
    load_contract_findings,
    summarize_docs_findings,
)
from .github_client import GitHubClientError, GitHubWriteClient
from .intake import is_docs_remediation_issue
from .models import ExecutionContract, ExecutionResult, IssueIntake, QaResult, RepairResult, RunRecord
from .opencode_model import resolve_opencode_model
from .rerun_context import latest_rejected_pull_request


@dataclass(frozen=True, slots=True)
class OpenCodeRepairAdapter:
    """Runs a real repair agent through the local `opencode` CLI."""

    binary: str = "opencode"
    agent: str = "build"
    model: str | None = None
    qa_feedback: str | None = None

    def repair(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
    ) -> RepairResult:
        stdout_path = run_dir / "repair.stdout.log"
        stderr_path = run_dir / "repair.stderr.log"
        patch_path = run_dir / "repair.patch"
        transcript_path = run_dir / "repair-transcript.json"

        prompt = _build_repair_prompt(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
            repo_workspace=repo_workspace,
            qa_feedback=self.qa_feedback,
        )

        command = [
            self.binary,
            "run",
            "--format",
            "json",
            "--agent",
            self.agent,
            "--dir",
            str(repo_workspace),
            "--dangerously-skip-permissions",
        ]
        resolved_model = resolve_opencode_model(self.model)
        if resolved_model:
            command.extend(["--model", resolved_model])
        command.append(prompt)

        command_result = subprocess.run(
            command,
            cwd=str(repo_workspace),
            capture_output=True,
            text=True,
        )
        stdout_path.write_text(command_result.stdout, encoding="utf-8", errors="ignore")
        stderr_path.write_text(command_result.stderr, encoding="utf-8", errors="ignore")
        transcript_path.write_text(
            json.dumps(_extract_json_events(command_result.stdout), indent=2) + "\n",
            encoding="utf-8",
        )

        diff_result = subprocess.run(
            ["git", "diff", "--binary"],
            cwd=str(repo_workspace),
            capture_output=True,
            text=True,
        )

        if diff_result.returncode != 0:
            return RepairResult(
                status="failed_infra",
                summary="Repair agent finished, but git diff could not inspect workspace changes.",
                detail_codes=("repair_diff_failed",),
                workspace_path=str(repo_workspace.parent),
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )

        patch_text = diff_result.stdout
        if patch_text.strip():
            patch_path.write_text(patch_text, encoding="utf-8")

        if command_result.returncode != 0:
            return RepairResult(
                status="blocked",
                summary="Repair agent exited non-zero after local execution contract extraction.",
                detail_codes=("repair_agent_failed",),
                workspace_path=str(repo_workspace.parent),
                patch_path=str(patch_path) if patch_text.strip() else None,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )

        if not patch_text.strip():
            return RepairResult(
                status="blocked",
                summary="Repair agent completed but did not produce any source changes.",
                detail_codes=("repair_produced_no_changes",),
                workspace_path=str(repo_workspace.parent),
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )

        return RepairResult(
            status="completed",
            summary="Repair agent completed and produced source changes.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repo_workspace.parent),
            patch_path=str(patch_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )


class RepairStage:
    """Prepares a clean workspace and delegates repair to an adapter."""

    def __init__(
        self,
        *,
        repo_path: Path,
        adapter: OpenCodeRepairAdapter | None,
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

        if self.adapter is None:
            return RepairResult(
                status="not_configured",
                summary=(
                    "A documented local execution contract was prepared, but no repair agent was configured."
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

        return self.adapter.repair(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
            repo_workspace=repo_workspace,
        )


class WorkspaceQaVerifier:
    """Runs a deterministic local QA check against a repaired workspace."""

    def verify(
        self,
        *,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
        iteration: int,
    ) -> QaResult:
        qa_stdout_path = run_dir / f"qa-{iteration}.stdout.log"
        qa_stderr_path = run_dir / f"qa-{iteration}.stderr.log"

        contract = _load_execution_contract(contract_artifact_dir)
        if contract is None:
            return QaResult(
                status="failed_infra",
                summary="QA verifier could not load the execution contract artifact.",
                detail_codes=("qa_contract_missing",),
                stdout_path=str(qa_stdout_path),
                stderr_path=str(qa_stderr_path),
            )
        if contract.qa_command is None:
            return QaResult(
                status="failed_infra",
                summary="QA verifier could not find a documented QA command in the execution contract.",
                detail_codes=("qa_command_missing",),
                stdout_path=str(qa_stdout_path),
                stderr_path=str(qa_stderr_path),
            )
        command = contract.qa_command

        env = os.environ.copy()
        setup_stdout_chunks: list[str] = []
        setup_stderr_chunks: list[str] = []
        bootstrap_result = _ensure_whitelisted_tools_available(command, repo_workspace, env)
        if bootstrap_result is not None:
            qa_stdout_path.write_text("", encoding="utf-8", errors="ignore")
            qa_stderr_path.write_text(bootstrap_result, encoding="utf-8", errors="ignore")
            return QaResult(
                status="failed_infra",
                summary=(
                    "QA verifier could not make the documented QA toolchain available locally."
                ),
                detail_codes=("qa_tool_bootstrap_failed",),
                command=command,
                stdout_path=str(qa_stdout_path),
                stderr_path=str(qa_stderr_path),
            )

        for setup_command in contract.setup_commands:
            setup_result = subprocess.run(
                ["pwsh", "-NoLogo", "-NoProfile", "-Command", setup_command],
                cwd=str(repo_workspace),
                env=env,
                capture_output=True,
                text=True,
            )
            setup_stdout_chunks.append(
                _format_qa_log_section(f"Setup command stdout: {setup_command}", setup_result.stdout)
            )
            setup_stderr_chunks.append(
                _format_qa_log_section(f"Setup command stderr: {setup_command}", setup_result.stderr)
            )
            if setup_result.returncode != 0:
                qa_stdout_path.write_text(
                    "".join(setup_stdout_chunks), encoding="utf-8", errors="ignore"
                )
                qa_stderr_path.write_text(
                    "".join(setup_stderr_chunks), encoding="utf-8", errors="ignore"
                )
                return QaResult(
                    status="failed_infra",
                    summary=(
                        "QA verifier could not complete the documented setup steps in the repair workspace."
                    ),
                    detail_codes=("qa_environment_setup_failed",),
                    command=command,
                    stdout_path=str(qa_stdout_path),
                    stderr_path=str(qa_stderr_path),
                )

        completed = subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-Command", command],
            cwd=str(repo_workspace),
            env=env,
            capture_output=True,
            text=True,
        )
        qa_stdout_path.write_text(
            "".join(setup_stdout_chunks)
            + _format_qa_log_section("QA command stdout", completed.stdout),
            encoding="utf-8",
            errors="ignore",
        )
        qa_stderr_path.write_text(
            "".join(setup_stderr_chunks)
            + _format_qa_log_section("QA command stderr", completed.stderr),
            encoding="utf-8",
            errors="ignore",
        )

        if completed.returncode == 0:
            return QaResult(
                status="passed",
                summary="Documented QA command passed in the repair workspace.",
                detail_codes=("qa_passed",),
                command=command,
                stdout_path=str(qa_stdout_path),
                stderr_path=str(qa_stderr_path),
            )

        classification = _classify_qa_command_failure(completed.stdout, completed.stderr, command)
        return QaResult(
            status=classification["status"],
            summary=classification["summary"],
            detail_codes=classification["detail_codes"],
            command=command,
            stdout_path=str(qa_stdout_path),
            stderr_path=str(qa_stderr_path),
        )


def run_repair_qa_loop(
    *,
    repo_path: Path,
    adapter: OpenCodeRepairAdapter | None,
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
            iteration_adapter = OpenCodeRepairAdapter(
                binary=adapter.binary,
                agent=adapter.agent,
                model=adapter.model,
                qa_feedback=qa_feedback,
            )
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
        if qa_result.status in {"passed", "provisional"}:
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
        dict.fromkeys(
            (*synthesis_result.detail_codes, *repair_result.detail_codes, *qa_codes)
        )
    )

    if (
        repair_result.status == "completed"
        and qa_result is not None
        and qa_result.status in {"passed", "provisional"}
    ):
        return ExecutionResult(
            status="completed",
            executor_name="docs+repair",
            summary=(
                "Documented local setup/test instructions were extracted, the repair stage produced "
                "source changes, and QA passed."
            ),
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
        )

    if qa_result is not None and qa_result.status in {"failed", "unrunnable", "failed_infra"}:
        status = "blocked" if qa_result.status in {"failed", "unrunnable"} else "failed_infra"
        return ExecutionResult(
            status=status,
            executor_name="docs+repair",
            summary=qa_result.summary,
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
        )

    if repair_result.status == "failed_infra":
        return ExecutionResult(
            status="failed_infra",
            executor_name="docs+repair",
            summary=repair_result.summary,
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
        )

    return ExecutionResult(
        status="blocked",
        executor_name="docs+repair",
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
                executor_name="docs+repair",
                summary=(
                    validation_scope_summary
                    or (
                        "Repository documentation blockers were identified, the docs-remediation "
                        "repair stage produced focused documentation changes, and the repaired "
                        "workspace now satisfies the same docs gate."
                    )
                ),
                detail_codes=detail_codes,
                artifact_dir=validation_result.artifact_dir,
                stdout_path=validation_result.stdout_path,
                stderr_path=validation_result.stderr_path,
            )

        return ExecutionResult(
            status=validation_result.status,
            executor_name="docs+repair",
            summary=validation_scope_summary or validation_result.summary,
            detail_codes=detail_codes,
            artifact_dir=validation_result.artifact_dir,
            stdout_path=validation_result.stdout_path,
            stderr_path=validation_result.stderr_path,
        )

    if repair_result.status == "completed":
        return ExecutionResult(
            status="failed_infra",
            executor_name="docs+repair",
            summary=(
                "Docs-remediation repair completed, but the repaired workspace was not revalidated."
            ),
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
        )

    if repair_result.status == "failed_infra":
        return ExecutionResult(
            status="failed_infra",
            executor_name="docs+repair",
            summary=repair_result.summary,
            detail_codes=detail_codes,
            artifact_dir=synthesis_result.artifact_dir,
            stdout_path=synthesis_result.stdout_path,
            stderr_path=synthesis_result.stderr_path,
        )

    return ExecutionResult(
        status="blocked",
        executor_name="docs+repair",
        summary=repair_result.summary,
        detail_codes=detail_codes,
        artifact_dir=synthesis_result.artifact_dir,
        stdout_path=synthesis_result.stdout_path,
        stderr_path=synthesis_result.stderr_path,
    )


def _build_repair_prompt(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    contract_artifact_dir: Path,
    repo_workspace: Path,
    qa_feedback: str | None,
) -> str:
    docs_fix_prompt_path = contract_artifact_dir / "docs-fix-prompt.txt"
    if is_docs_remediation_issue(intake):
        target_rule_ids = {
            str(finding.get("rule_id", "")).strip()
            for finding in extract_docs_target_findings(intake.issue.body)
        }
        lines = [
            "Repair the issue in this repository workspace.",
            f"Run ID: {run_record.run_id}",
            f"Issue: {intake.issue.reference}",
            f"Title: {intake.issue.title}",
            "Requirements:",
            "- Update repository documentation in the current workspace to resolve the issue.",
            "- Treat this as a docs-remediation issue, not a product code change.",
            "- Use the docs-fix prompt, execution contract, and executor logs as the source of truth.",
            "- Eliminate every tracked target finding in this issue's hidden target-findings metadata.",
            "- Prefer one exact canonical command path. Do not document multiple alternatives unless the target findings explicitly require ambiguity removal and one option is marked canonical.",
            "- If a deterministic path is impossible to document, say that explicitly in the docs rather than disguising uncertainty with advice like restart your shell, maybe, if prompted, should, or typically.",
            "- The goal is not to make the docs more helpful in general; the goal is to make the tracked findings disappear under the same extractor and checklist.",
            "- Keep changes minimal and focused.",
            "- Do not ask questions.",
            "- Do not commit.",
            "- After edits, stop with a short summary.",
            "Context files:",
            f"- Issue statement: {run_dir / 'issue.md'}",
            f"- Docs fix prompt: {docs_fix_prompt_path}",
            f"- Execution contract: {contract_artifact_dir / 'contract.json'}",
            f"- README snapshot: {contract_artifact_dir / 'README.snapshot.md'}",
            f"- Executor stdout log: {run_dir / 'executor.stdout.log'}",
            f"- Executor stderr log: {run_dir / 'executor.stderr.log'}",
            f"Workspace repo: {repo_workspace}",
        ]
        if "docs_setup_prerequisite_manual_only" in target_rule_ids:
            lines.insert(
                8,
                "- When the target finding is `docs_setup_prerequisite_manual_only`, include at least one exact executable acquisition or install command for the prerequisite in a fenced code block.",
            )
        if "docs_setup_prerequisite_source_unambiguous" in target_rule_ids:
            lines.insert(
                9,
                "- When the target finding is `docs_setup_prerequisite_source_unambiguous`, explicitly label the canonical source as one of: `release artifact`, `package manager`, or `source build`.",
            )
        if "docs_environment_assumptions_explicit" in target_rule_ids:
            lines.insert(
                10,
                "- When the target finding is `docs_environment_assumptions_explicit`, include a literal `Environment assumptions:` line in the edited docs section and spell the assumptions out directly.",
            )
    else:
        lines = [
            "Repair the issue in this repository workspace.",
            f"Run ID: {run_record.run_id}",
            f"Issue: {intake.issue.reference}",
            f"Title: {intake.issue.title}",
            "Requirements:",
            "- Modify code in the current workspace to resolve the issue.",
            "- Use the documented local setup/test contract as the source of truth.",
            "- Do not ask questions.",
            "- Keep changes minimal and focused.",
            "- Do not commit.",
            "- After edits, stop with a short summary.",
            "Context files:",
            f"- Issue statement: {run_dir / 'issue.md'}",
            f"- Execution contract: {contract_artifact_dir / 'contract.json'}",
            f"- README snapshot: {contract_artifact_dir / 'README.snapshot.md'}",
            f"- Executor stdout log: {run_dir / 'executor.stdout.log'}",
            f"- Executor stderr log: {run_dir / 'executor.stderr.log'}",
            f"Workspace repo: {repo_workspace}",
        ]
        if docs_fix_prompt_path.exists():
            lines.insert(-1, f"- Docs fix prompt: {docs_fix_prompt_path}")
    if qa_feedback:
        lines.extend(["QA feedback from the previous attempt:", qa_feedback])
    return "\n".join(lines)


def run_docs_remediation_repair(
    *,
    repo_path: Path,
    adapter: OpenCodeRepairAdapter | None,
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
            "The docs-remediation issue is still blocked because one or more target findings remain. "
            f"Remaining target findings: {unresolved_summary}"
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
            "The docs-remediation issue cleared its target findings, but new untracked docs blockers were "
            f"introduced or surfaced: {new_summary}"
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
            "The docs-remediation issue cleared all target findings. Remaining docs blockers are baseline "
            f"findings already tracked elsewhere: {baseline_summary}"
        )
    else:
        summary = (
            "The docs-remediation issue cleared all tracked target findings and did not surface any new docs "
            "blockers."
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


def _extract_json_events(stdout: str) -> list[dict]:
    events: list[dict] = []
    for line in stdout.splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def build_qa_feedback(qa_result: QaResult) -> str:
    stdout_excerpt = ""
    stderr_excerpt = ""
    if qa_result.stdout_path:
        stdout_excerpt = Path(qa_result.stdout_path).read_text(encoding="utf-8", errors="ignore")
    if qa_result.stderr_path:
        stderr_excerpt = Path(qa_result.stderr_path).read_text(encoding="utf-8", errors="ignore")
    excerpt = (stdout_excerpt + "\n" + stderr_excerpt).strip()
    excerpt = excerpt[-4000:]
    return "\n".join(
        [
            f"QA command: {qa_result.command}",
            f"QA summary: {qa_result.summary}",
            "QA output excerpt:",
            excerpt,
        ]
    )


def _format_qa_log_section(title: str, content: str) -> str:
    body = content.rstrip()
    return f"===== {title} =====\n{body}\n"


def _run_baseline_qa(
    *,
    repo_path: Path,
    run_dir: Path,
    contract_artifact_dir: Path,
    verifier: WorkspaceQaVerifier,
    rerun_branch: str | None = None,
    rerun_remote_url: str | None = None,
) -> QaResult:
    baseline_workspace = (run_dir / "baseline-workspace").resolve()
    baseline_repo = (baseline_workspace / "repo").resolve()
    baseline_workspace.mkdir(parents=True, exist_ok=True)
    if baseline_repo.exists():
        shutil.rmtree(baseline_repo)

    clone_result = subprocess.run(
        ["git", "clone", "--no-hardlinks", str(repo_path.resolve()), str(baseline_repo)],
        cwd=str(baseline_workspace),
        capture_output=True,
        text=True,
    )
    if clone_result.returncode != 0:
        return QaResult(
            status="failed_infra",
            summary="Baseline QA could not clone the source repository.",
            detail_codes=("baseline_clone_failed",),
            phase="baseline",
        )

    rerun_reset_error = _reset_workspace_to_rerun_branch(
        baseline_repo,
        branch_name=rerun_branch,
        remote_url=rerun_remote_url,
    )
    if rerun_reset_error is not None:
        return QaResult(
            status="failed_infra",
            summary=rerun_reset_error,
            detail_codes=("baseline_rerun_branch_unavailable",),
            phase="baseline",
        )

    result = verifier.verify(
        run_dir=run_dir,
        contract_artifact_dir=contract_artifact_dir,
        repo_workspace=baseline_repo,
        iteration=0,
    )
    return QaResult(
        status=result.status,
        summary=result.summary,
        detail_codes=result.detail_codes,
        command=result.command,
        stdout_path=result.stdout_path,
        stderr_path=result.stderr_path,
        phase="baseline",
    )


def _finalize_qa_result(
    *,
    qa_result: QaResult,
    baseline_result: QaResult,
    baseline_failure_signature: frozenset[str],
) -> QaResult:
    final_result = QaResult(
        status=qa_result.status,
        summary=qa_result.summary,
        detail_codes=qa_result.detail_codes,
        command=qa_result.command,
        stdout_path=qa_result.stdout_path,
        stderr_path=qa_result.stderr_path,
        phase="final",
    )
    if baseline_result.status not in {"failed", "failed_infra"}:
        return final_result
    if qa_result.status not in {"failed", "failed_infra"}:
        return final_result

    repaired_failure_signature = _failure_signature(qa_result)
    if repaired_failure_signature < baseline_failure_signature:
        return QaResult(
            status="provisional",
            summary=(
                "Repair QA improved on the baseline failure set without introducing "
                "new failures, but the suite is not fully green."
            ),
            detail_codes=("qa_baseline_improved",),
            command=qa_result.command,
            stdout_path=qa_result.stdout_path,
            stderr_path=qa_result.stderr_path,
            phase="final",
        )

    return final_result


def _failure_signature(qa_result: QaResult) -> frozenset[str]:
    combined_output = ""
    if qa_result.stdout_path and Path(qa_result.stdout_path).exists():
        combined_output += Path(qa_result.stdout_path).read_text(encoding="utf-8", errors="ignore")
    if qa_result.stderr_path and Path(qa_result.stderr_path).exists():
        combined_output += "\n" + Path(qa_result.stderr_path).read_text(
            encoding="utf-8", errors="ignore"
        )

    markers: set[str] = set()
    for line in combined_output.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("ERROR "):
            markers.add(text)
        elif text.startswith("E   "):
            markers.add(text)
    return frozenset(markers)


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
            "Repair rerun could not reset the workspace to the previous rejected pull request branch "
            f"`{branch_name}`."
        )
    return None

def _load_execution_contract(contract_artifact_dir: Path) -> ExecutionContract | None:
    contract_path = contract_artifact_dir / "contract.json"
    if not contract_path.exists():
        return None
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    setup_commands = payload.get("setup_commands", [])
    notes = payload.get("notes", [])
    questions = payload.get("questions", [])
    return ExecutionContract(
        source_path=payload.get("source_path"),
        setup_commands=tuple(str(item) for item in setup_commands),
        qa_command=payload.get("qa_command"),
        notes=tuple(str(item) for item in notes),
        questions=tuple(str(item) for item in questions),
    )


def _ensure_whitelisted_tools_available(
    command: str, repo_workspace: Path, env: dict[str, str]
) -> str | None:
    tool_name = _leading_tool(command)
    if tool_name not in {"uv", "poetry"}:
        return None

    probe = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-Command", f"{tool_name} --version"],
        cwd=str(repo_workspace),
        env=env,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        return None

    install_command = f"python -m pip install {tool_name}"
    installed = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-Command", install_command],
        cwd=str(repo_workspace),
        env=env,
        capture_output=True,
        text=True,
    )
    if installed.returncode == 0:
        return None

    return (
        f"Could not install required QA tool `{tool_name}`. The documented QA command is `{command}`, "
        f"so the workflow tried the whitelisted bootstrap command `{install_command}` and it failed. "
        "A newcomer would now ask: is this tool really part of the documented setup, and if so, "
        "what exact installation command should they run on Windows?\n\n"
        f"stdout:\n{installed.stdout}\n\nstderr:\n{installed.stderr}"
    )


def _leading_tool(command: str) -> str:
    stripped = command.strip()
    if not stripped:
        return ""
    return stripped.split(maxsplit=1)[0]


def _classify_qa_command_failure(
    stdout: str, stderr: str, command: str
) -> dict[str, Literal["failed", "unrunnable"] | str | tuple[str, ...]]:
    combined = f"{stdout}\n{stderr}".lower()

    unrunnable_markers = (
        "commandnotfoundexception",
        "is not recognized as the name of a cmdlet",
        "usage: pytest",
        "error: unrecognized arguments:",
        "error: file or directory not found:",
        "collected 0 items",
        "no tests ran",
        "no tests collected",
        "importerror while loading conftest",
        "pytestusageerror",
    )
    if any(marker in combined for marker in unrunnable_markers):
        return {
            "status": "unrunnable",
            "summary": (
                "The documented QA command did not produce a trustworthy verification signal. "
                "It appears to have failed before actually verifying the fix."
            ),
            "detail_codes": ("qa_command_unrunnable",),
        }

    if "pytest" in command.lower():
        if "failed" in combined or "error" in combined:
            return {
                "status": "failed",
                "summary": "Documented QA command ran and reported failing checks in the repair workspace.",
                "detail_codes": ("qa_failed",),
            }
        return {
            "status": "unrunnable",
            "summary": (
                "The documented QA command exited non-zero, but the output does not clearly show "
                "that it reached a valid verification result."
            ),
            "detail_codes": ("qa_command_unrunnable",),
        }

    return {
        "status": "unrunnable",
        "summary": (
            "The documented QA command exited non-zero without a clear verification result. "
            "Treating this as an unrunnable verification command instead of a real failing check."
        ),
        "detail_codes": ("qa_command_unrunnable",),
    }
