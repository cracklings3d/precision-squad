"""Repair-agent adapter and prompt construction."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from jsonschema import ValidationError, validate

from ..docs_remediation import extract_docs_target_findings
from ..intake import is_docs_remediation_issue
from ..models import IssueIntake, RepairResult, RunRecord, SideIssue
from ..opencode_model import resolve_opencode_model


@runtime_checkable
class RepairAdapter(Protocol):
    """Common interface for repair adapters."""

    def repair(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
    ) -> RepairResult: ...

    def with_qa_feedback(self, feedback: str) -> RepairAdapter: ...

REPAIR_RESULT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "What the agent did — one paragraph max.",
        },
        "side_issues": {
            "type": "array",
            "description": "Secondary issues discovered that are unrelated to the primary issue.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "One-line issue identifier.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Concise synthesis of the finding — what needs fixing and why. Aim for ~500 chars.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Full verbose output for audit purposes.",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "GitHub labels to apply to the follow-up issue.",
                    },
                },
                "required": ["title", "summary", "body"],
            },
        },
    },
    "required": ["summary"],
}


@dataclass(frozen=True, slots=True)
class OpenCodeRepairAdapter:
    """Runs a real repair agent through the local `opencode` CLI."""

    binary: str = "opencode"
    agent: str = "build"
    model: str | None = None
    qa_feedback: str | None = None

    def with_qa_feedback(self, feedback: str) -> OpenCodeRepairAdapter:
        """Return a copy of this adapter with the given QA feedback."""
        return OpenCodeRepairAdapter(
            binary=self.binary,
            agent=self.agent,
            model=self.model,
            qa_feedback=feedback,
        )

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

        repair_json = _parse_repair_json(command_result.stdout)
        side_issues: tuple[SideIssue, ...] = ()
        if repair_json is not None:
            side_issues = _extract_side_issues(repair_json)

        return RepairResult(
            status="completed",
            summary=repair_json.get("summary") if repair_json else "Repair agent completed and produced source changes.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repo_workspace.parent),
            patch_path=str(patch_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            side_issues=side_issues,
        )


def _parse_repair_json(stdout: str) -> dict | None:
    """Parse and validate JSON output from the repair agent."""
    events = _extract_json_events(stdout)
    if not events:
        return None
    last_event = events[-1]
    if not isinstance(last_event, dict):
        return None
    try:
        validate(instance=last_event, schema=REPAIR_RESULT_SCHEMA)
    except ValidationError:
        return None
    return last_event


def _extract_side_issues(repair_json: dict) -> tuple[SideIssue, ...]:
    """Extract side issues from parsed JSON, returning empty tuple on validation failure."""
    side_issues_data = repair_json.get("side_issues")
    if not isinstance(side_issues_data, list):
        return ()
    side_issues: list[SideIssue] = []
    for item in side_issues_data:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        summary = item.get("summary")
        body = item.get("body", "")
        if not isinstance(title, str) or not isinstance(summary, str):
            continue
        labels_raw = item.get("labels", [])
        if isinstance(labels_raw, list):
            labels = tuple(str(l) for l in labels_raw if isinstance(l, str))
        else:
            labels = ()
        side_issues.append(SideIssue(
            title=title,
            summary=summary,
            body=body,
            labels=labels,
        ))
    return tuple(side_issues)


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
    docs_fix_prompt_content = ""
    if docs_fix_prompt_path.exists():
        docs_fix_prompt_content = docs_fix_prompt_path.read_text(encoding="utf-8")

    json_instruction = (
        "Output a single JSON object with at least a `summary` field describing what you did. "
        "If you discover secondary issues unrelated to the primary issue, include them in a `side_issues` array. "
        "Each side issue must have `title` (one-line identifier), `summary` (concise synthesis, aim for ~500 chars), "
        "`body` (full verbose output for audit), and `labels` (array of GitHub label strings). "
        "Schema:\n"
        + json.dumps(REPAIR_RESULT_SCHEMA, indent=2)
    )

    if is_docs_remediation_issue(intake):
        lines = _build_docs_remediation_prompt(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
            repo_workspace=repo_workspace,
            docs_fix_prompt_content=docs_fix_prompt_content,
            json_instruction=json_instruction,
        )
    else:
        lines = _build_standard_repair_prompt(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
            repo_workspace=repo_workspace,
            docs_fix_prompt_content=docs_fix_prompt_content,
            json_instruction=json_instruction,
        )
    if qa_feedback:
        lines.extend(["QA feedback from the previous attempt:", qa_feedback])
    return "\n".join(lines)


def _build_docs_remediation_prompt(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    contract_artifact_dir: Path,
    repo_workspace: Path,
    docs_fix_prompt_content: str,
    json_instruction: str,
) -> list[str]:
    """Build prompt for docs-remediation issues."""
    target_rule_ids = {
        str(finding.get("rule_id", "")).strip()
        for finding in extract_docs_target_findings(intake.issue.body)
    }
    # Build conditional requirements based on target rule IDs
    conditional_requirements: list[str] = []
    if "docs_setup_prerequisite_manual_only" in target_rule_ids:
        conditional_requirements.append(
            "- When the target finding is `docs_setup_prerequisite_manual_only`, "
            "include at least one exact executable acquisition or install "
            "command for the prerequisite in a fenced code block.",
        )
    if "docs_setup_prerequisite_source_unambiguous" in target_rule_ids:
        conditional_requirements.append(
            "- When the target finding is `docs_setup_prerequisite_source_unambiguous`, "
            "explicitly label the canonical source as one of: `release artifact`, "
            "`package manager`, or `source build`.",
        )
    if "docs_environment_assumptions_explicit" in target_rule_ids:
        conditional_requirements.append(
            "- When the target finding is `docs_environment_assumptions_explicit`, "
            "include a literal `Environment assumptions:` line in the edited "
            "docs section and spell the assumptions out directly.",
        )
    return [
        "Repair the issue in this repository workspace.",
        f"Run ID: {run_record.run_id}",
        f"Issue: {intake.issue.reference}",
        f"Title: {intake.issue.title}",
        "Requirements:",
        "- Update repository documentation in the current workspace to resolve the issue.",
        "- Treat this as a docs-remediation issue, not a product code change.",
        "- Use the docs-fix prompt (inlined below), execution contract, and executor logs as "
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
        *conditional_requirements,
        "- Keep changes minimal and focused.",
        "- Do not ask questions.",
        "- Do not commit.",
        "- After edits, output your JSON result.",
        "Context files:",
        f"- Issue statement: {run_dir / 'issue.md'}",
        f"- Docs fix prompt (inlined):\n\n{docs_fix_prompt_content}\n",
        f"- Execution contract: {contract_artifact_dir / 'contract.json'}",
        f"- README snapshot: {contract_artifact_dir / 'README.snapshot.md'}",
        f"- Executor stdout log: {run_dir / 'executor.stdout.log'}",
        f"- Executor stderr log: {run_dir / 'executor.stderr.log'}",
        f"Workspace repo: {repo_workspace}",
        "",
        json_instruction,
    ]


def _build_standard_repair_prompt(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    contract_artifact_dir: Path,
    repo_workspace: Path,
    docs_fix_prompt_content: str,
    json_instruction: str,
) -> list[str]:
    """Build prompt for standard repair issues."""
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
        "- After edits, output your JSON result.",
        "Context files:",
        f"- Issue statement: {run_dir / 'issue.md'}",
        f"- Execution contract: {contract_artifact_dir / 'contract.json'}",
        f"- README snapshot: {contract_artifact_dir / 'README.snapshot.md'}",
        f"- Executor stdout log: {run_dir / 'executor.stdout.log'}",
        f"- Executor stderr log: {run_dir / 'executor.stderr.log'}",
        f"Workspace repo: {repo_workspace}",
    ]
    if docs_fix_prompt_content:
        lines.insert(
            -2,
            "- The following secondary issues were detected in the documentation "
            "but are not the primary focus of this repair. "
            "Recommend surfacing them as separate GitHub issues via the JSON output:\n"
            + f"\n{docs_fix_prompt_content}\n",
        )
    lines.insert(-1, json_instruction)
    return lines
