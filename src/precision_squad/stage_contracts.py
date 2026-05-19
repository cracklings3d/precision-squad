"""Explicit downstream stage contracts for developer and review stages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .docs_policy import load_review_checklist_rules
from .models import ApprovedPlan, IssueIntake, RunRecord
from .run_store import RunStore

DOCS_CHECKLIST_SOURCE = "src/precision_squad/data/docs_checklist.json"
_SURFACED_DESIGN_DECISIONS_EMPTY = (
    "none (reserved for issue #55; intentionally empty for issue #54)"
)


@dataclass(frozen=True, slots=True)
class DeveloperStageContract:
    """Explicit allowlisted inputs for developer-stage prompt assembly."""

    approved_plan: ApprovedPlan
    run_id: str
    issue_ref: str
    issue_title: str
    issue_statement_path: Path
    execution_contract_path: Path
    readme_snapshot_path: Path
    executor_stdout_path: Path
    executor_stderr_path: Path
    repo_workspace: Path
    docs_fix_prompt_content: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewStageContract:
    """Explicit allowlisted inputs for review-stage prompt assembly."""

    approved_plan_text: str
    pr_diff: str
    checklist_rules: tuple[dict[str, Any], ...]
    run_id: str
    issue_ref: str
    pull_request_url: str
    pull_number: int | None
    pull_head_sha: str | None
    surfaced_design_decisions: str = _SURFACED_DESIGN_DECISIONS_EMPTY


def load_developer_stage_contract(
    *,
    approved_plan: ApprovedPlan,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    contract_artifact_dir: Path,
    repo_workspace: Path,
) -> DeveloperStageContract:
    """Load and validate the explicit developer-stage contract inputs."""
    issue_statement_path = _require_file(
        run_dir / "issue.md",
        "issue statement artifact",
    )
    execution_contract_path = _require_file(
        contract_artifact_dir / "contract.json",
        "execution contract artifact",
    )
    readme_snapshot_path = _require_file(
        contract_artifact_dir / "README.snapshot.md",
        "README snapshot artifact",
    )
    executor_stdout_path = _require_file(
        run_dir / "executor.stdout.log",
        "executor stdout log",
    )
    executor_stderr_path = _require_file(
        run_dir / "executor.stderr.log",
        "executor stderr log",
    )

    docs_fix_prompt_path = contract_artifact_dir / "docs-fix-prompt.txt"
    docs_fix_prompt_content = None
    if docs_fix_prompt_path.exists():
        docs_fix_prompt_content = docs_fix_prompt_path.read_text(encoding="utf-8")

    return DeveloperStageContract(
        approved_plan=approved_plan,
        run_id=run_record.run_id,
        issue_ref=str(intake.issue.reference),
        issue_title=intake.issue.title,
        issue_statement_path=issue_statement_path,
        execution_contract_path=execution_contract_path,
        readme_snapshot_path=readme_snapshot_path,
        executor_stdout_path=executor_stdout_path,
        executor_stderr_path=executor_stderr_path,
        repo_workspace=repo_workspace,
        docs_fix_prompt_content=docs_fix_prompt_content,
    )


def load_review_stage_contract(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    pull_request_url: str,
    pull_number: int | None,
    pull_head_sha: str | None,
    diff_loader: Callable[[str, str, str], str],
) -> ReviewStageContract:
    """Load and validate the explicit review-stage contract inputs."""
    approved_plan_text = RunStore.load_approved_plan_text(
        run_dir,
        issue_ref=run_record.issue_ref,
        include_named_references=True,
    )
    if not approved_plan_text.strip():
        raise ValueError("Review context pack is missing required approved plan")

    pr_diff = diff_loader(
        intake.issue.reference.owner,
        intake.issue.reference.repo,
        pull_request_url,
    )
    if not pr_diff.strip():
        raise ValueError("Review context pack is missing required PR diff")

    checklist_rules = load_review_checklist_rules()
    if not checklist_rules:
        raise ValueError("Review context pack is missing required checklist material")

    return ReviewStageContract(
        approved_plan_text=approved_plan_text,
        pr_diff=pr_diff,
        checklist_rules=checklist_rules,
        run_id=run_record.run_id,
        issue_ref=str(intake.issue.reference),
        pull_request_url=pull_request_url,
        pull_number=pull_number,
        pull_head_sha=pull_head_sha,
    )


def render_developer_approved_plan_context(approved_plan: ApprovedPlan | None) -> list[str]:
    """Render approved-plan context for developer prompts from the canonical artifact only."""
    if approved_plan is None:
        return []
    lines = [
        "Approved plan:",
        f"- Summary: {approved_plan.plan_summary}",
        "- Implementation steps:",
        *[f"  - {step}" for step in approved_plan.implementation_steps],
        f"- Retrieval surface summary: {approved_plan.retrieval_surface_summary or '(empty)'}",
    ]
    if approved_plan.named_references:
        lines.append("- Named references:")
        for ref in approved_plan.named_references:
            suffix = f": {ref.description}" if ref.description else ""
            lines.append(f"  - {ref.name} ({ref.reference_type}){suffix}")
    else:
        lines.append("- Named references: (none)")
    return lines


def render_review_prompt(role: str, contract: ReviewStageContract) -> str:
    """Render a review prompt from the explicit review-stage contract."""
    checklist_lines: list[str] = []
    for rule in contract.checklist_rules:
        checklist_lines.extend(
            [
                f"- [{_blocking_marker(rule)}] {rule['code']}: {rule['requirement']}",
                f"  Question: {rule['question']}",
            ]
        )
    metadata_lines = [
        f"Review role: {role}",
        f"Run ID: {contract.run_id}",
        f"Issue: {contract.issue_ref}",
        f"PR: {contract.pull_request_url}",
        "PR Number: "
        f"{contract.pull_number if contract.pull_number is not None else '(unavailable)'}",
        f"PR Head SHA: {contract.pull_head_sha or '(unavailable)'}",
    ]
    return "\n".join(
        [
            *metadata_lines,
            "",
            "## Approved Plan",
            contract.approved_plan_text,
            "",
            f"## Deterministic Review Checklist ({DOCS_CHECKLIST_SOURCE})",
            *checklist_lines,
            "",
            "## Surfaced Design Decisions",
            f"- {contract.surfaced_design_decisions}",
            "",
            "## PR Diff",
            contract.pr_diff,
            "",
            "Review the published PR and respond with exactly one JSON object.",
            'Use the shape: {"status":"approved|rejected","summary":"...","feedback":["..."]}',
            "If you reject, feedback must contain concrete required changes.",
            "Do not include markdown fences.",
        ]
    )


def _require_file(path: Path, label: str) -> Path:
    if not path.exists() or not path.is_file():
        raise ValueError(f"Repair stage is missing required {label}: {path}")
    return path


def _blocking_marker(rule: dict[str, Any]) -> str:
    return "blocking" if bool(rule.get("blocking")) else "advisory"
