"""Repair-agent adapter and prompt construction."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..docs_remediation import extract_docs_target_findings
from ..intake import is_docs_remediation_issue
from ..models import IssueIntake, RepairResult, RunRecord
from ..opencode_model import resolve_opencode_model


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
            "- Use the docs-fix prompt, execution contract, and executor logs as "
            "the source of truth.",
            "- Eliminate every tracked target finding in this issue's hidden "
            "target-findings metadata.",
            "- Prefer one exact canonical command path. Do not document multiple "
            "alternatives unless the target findings explicitly require ambiguity "
            "removal and one option is marked canonical.",
            "- If a deterministic path is impossible to document, say that "
            "explicitly in the docs rather than disguising uncertainty with advice "
            "like restart your shell, maybe, if prompted, should, or typically.",
            "- The goal is not to make the docs more helpful in general; the goal "
            "is to make the tracked findings disappear under the same extractor and "
            "checklist.",
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
                "- When the target finding is `docs_setup_prerequisite_manual_only`, "
                "include at least one exact executable acquisition or install "
                "command for the prerequisite in a fenced code block.",
            )
        if "docs_setup_prerequisite_source_unambiguous" in target_rule_ids:
            lines.insert(
                9,
                "- When the target finding is `docs_setup_prerequisite_source_unambiguous`, "
                "explicitly label the canonical source as one of: `release artifact`, "
                "`package manager`, or `source build`.",
            )
        if "docs_environment_assumptions_explicit" in target_rule_ids:
            lines.insert(
                10,
                "- When the target finding is `docs_environment_assumptions_explicit`, "
                "include a literal `Environment assumptions:` line in the edited "
                "docs section and spell the assumptions out directly.",
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
