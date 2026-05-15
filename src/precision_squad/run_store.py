"""Filesystem-backed run persistence."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from .models import (
    ApprovedPlan,
    EvaluationResult,
    ExecutionResult,
    GovernanceVerdict,
    IssueIntake,
    NamedReference,
    PostPublishReviewResult,
    PublishPlan,
    PublishResult,
    QaResult,
    RepairResult,
    RunRecord,
    RunRequest,
)

PersistedArtifact = (
    ApprovedPlan
    | EvaluationResult
    | ExecutionResult
    | GovernanceVerdict
    | IssueIntake
    | PostPublishReviewResult
    | PublishPlan
    | PublishResult
    | QaResult
    | RepairResult
    | RunRecord
    | RunRequest
)


class RunStore:
    """Persist run artifacts under a local runs directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_run(self, request: RunRequest, intake: IssueIntake) -> RunRecord:
        created_at = _utc_now()
        run_id = _build_run_id(created_at)
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        status = "blocked" if intake.assessment.status == "blocked" else "runnable"
        record = RunRecord(
            run_id=run_id,
            issue_ref=request.issue_ref,
            status=status,
            created_at=created_at,
            updated_at=created_at,
            run_dir=str(run_dir),
        )

        self._write_json(run_dir / "run-request.json", request)
        self._write_json(run_dir / "issue-intake.json", intake)
        self._write_issue_context(run_dir / "issue.md", intake)
        self._write_json(run_dir / "run-record.json", record)
        return record

    def load_run(self, run_id: str) -> RunRecord:
        """Load an existing run record by run ID."""
        run_dir = self.root / run_id
        record_path = run_dir / "run-record.json"
        if not record_path.exists():
            raise ValueError(f"Run record not found: {record_path}")
        return _read_run_record(record_path)

    def write_run_record(self, record: RunRecord) -> None:
        """Write an updated run record."""
        run_dir = Path(record.run_dir).resolve()
        self._write_json(run_dir / "run-record.json", record)

    def write_execution_result(self, run_dir: Path, result: ExecutionResult) -> None:
        self._write_json(run_dir / "execution-result.json", result)

    def write_approved_plan(self, run_dir: Path, plan: ApprovedPlan) -> None:
        self._write_json(run_dir / "approved-plan.json", plan)

    @staticmethod
    def load_approved_plan(run_dir: Path) -> ApprovedPlan | None:
        plan_path = run_dir / "approved-plan.json"
        if not plan_path.exists():
            return None
        return _read_approved_plan(plan_path)

    @staticmethod
    def load_approved_plan_text(
        run_dir: Path,
        include_named_references: bool = False,
    ) -> str | None:
        """Load the approved plan and render it as markdown text, or None if not present."""
        plan = RunStore.load_approved_plan(run_dir)
        if plan is None:
            return None
        return render_approved_plan_text(plan, include_named_references=include_named_references)

    def write_evaluation_result(self, run_dir: Path, result: EvaluationResult) -> None:
        self._write_json(run_dir / "evaluation-result.json", result)

    def write_repair_result(self, run_dir: Path, result: RepairResult) -> None:
        self._write_json(run_dir / "repair-result.json", result)

    def write_qa_result(self, run_dir: Path, result: QaResult) -> None:
        suffix = "" if result.phase in {"repair", "final"} else f"-{result.phase}"
        self._write_json(run_dir / f"qa{suffix}-result.json", result)
        if result.phase == "final":
            self._write_json(run_dir / "qa-result.json", result)

    def write_governance_verdict(self, run_dir: Path, verdict: GovernanceVerdict) -> None:
        self._write_json(run_dir / "governance-verdict.json", verdict)

    def write_publish_plan(self, run_dir: Path, plan: PublishPlan) -> None:
        self._write_json(run_dir / "publish-plan.json", plan)

    def write_publish_result(self, run_dir: Path, result: PublishResult) -> None:
        self._write_json(run_dir / "publish-result.json", result)

    def write_post_publish_review_result(
        self, run_dir: Path, result: PostPublishReviewResult
    ) -> None:
        self._write_json(run_dir / "post-publish-review-result.json", result)

    @staticmethod
    def _write_json(path: Path, payload: PersistedArtifact) -> None:
        path.write_text(
            json.dumps(asdict(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_issue_context(path: Path, intake: IssueIntake) -> None:
        issue = intake.issue
        sections = [
            f"# {issue.title}",
            "",
            f"Issue: {issue.reference}",
            f"URL: {issue.html_url}",
            "",
            "## Summary",
            intake.summary,
            "",
            "## Problem Statement",
            intake.problem_statement,
            "",
            "## Issue Body",
            issue.body or "(empty)",
        ]
        if issue.comments:
            sections.extend(["", "## Issue Comments"])
            for index, comment in enumerate(issue.comments, start=1):
                sections.extend(["", f"### Comment {index}", comment])
        path.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_run_id(created_at: str) -> str:
    stamp = created_at.replace(":", "").replace("-", "")
    stamp = stamp.replace("T", "-").replace("Z", "")
    return f"run-{stamp}-{uuid4().hex[:8]}"


def _read_run_record(path: Path) -> RunRecord:
    """Read a run record from a JSON file."""
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    status = cast(
        Literal["intake_complete", "blocked", "runnable"],
        str(payload["status"]),
    )
    return RunRecord(
        run_id=str(payload["run_id"]),
        issue_ref=str(payload["issue_ref"]),
        status=status,
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
        run_dir=str(payload["run_dir"]),
        attempt=int(payload.get("attempt", 1)),
    )


def _read_approved_plan(path: Path) -> ApprovedPlan:
    """Read an approved plan from a JSON file."""
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    if "issue_ref" not in payload:
        raise ValueError("Approved plan is missing required field 'issue_ref'")
    plan_issue_ref = _require_non_empty_str(payload.get("issue_ref"), field_name="issue_ref")
    plan_summary = _require_non_empty_str(payload.get("plan_summary"), field_name="plan_summary")
    implementation_steps = _read_implementation_steps(payload)
    approved = _read_approved_flag(payload)
    named_references_raw = payload.get("named_references", [])
    if not isinstance(named_references_raw, list):
        raise ValueError("Expected 'named_references' to be a list")
    named_refs: list[NamedReference] = []
    allowed_types = {"file", "interface", "symbol", "example"}
    for ref in named_references_raw:
        if isinstance(ref, dict):
            name = str(ref.get("name", ""))
            if not name:
                raise ValueError("Named reference has empty name")
            ref_type = ref.get("reference_type", "file")
            if ref_type not in allowed_types:
                raise ValueError(
                    f"Named reference has invalid reference_type '{ref_type}'; expected one of {allowed_types}"
                )
            named_refs.append(
                NamedReference(
                    name=name,
                    reference_type=ref_type,
                    description=str(ref.get("description", "")),
                )
            )
        else:
            named_refs.append(NamedReference(name=str(ref)))
    return ApprovedPlan(
        issue_ref=plan_issue_ref,
        plan_summary=plan_summary,
        implementation_steps=implementation_steps,
        named_references=tuple(named_refs),
        retrieval_surface_summary=str(payload.get("retrieval_surface_summary", "")),
        approved=approved,
    )


def _require_non_empty_str(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Approved plan field '{field_name}' must be a string")
    if not value.strip():
        raise ValueError(f"Approved plan is missing a non-empty '{field_name}'")
    return value


def _read_implementation_steps(payload: dict[str, object]) -> tuple[str, ...]:
    implementation_steps_raw = payload.get("implementation_steps", [])
    if not isinstance(implementation_steps_raw, list):
        raise ValueError("Expected 'implementation_steps' to be a list")
    implementation_steps = tuple(str(step) for step in implementation_steps_raw)
    if not implementation_steps:
        raise ValueError("Approved plan has no implementation steps")
    return implementation_steps


def _read_approved_flag(payload: dict[str, object]) -> bool:
    approved_raw = payload.get("approved", True)
    if not isinstance(approved_raw, bool):
        raise ValueError("Approved plan field 'approved' must be a boolean")
    if not approved_raw:
        raise ValueError("Approved plan must have 'approved': true")
    return approved_raw


def render_approved_plan_text(
    plan: ApprovedPlan,
    include_named_references: bool = False,
) -> str:
    """Render an ApprovedPlan to markdown text for context packs."""
    approval_marker = "Approved Plan"
    lines = [
        f"# {approval_marker}: {plan.issue_ref}",
        "",
        plan.plan_summary,
        "",
        "## Implementation Steps",
    ]
    for step in plan.implementation_steps:
        lines.append(f"- {step}")
    if plan.retrieval_surface_summary:
        lines.extend(["", f"**Retrieval Surface:** {plan.retrieval_surface_summary}"])
    if include_named_references and plan.named_references:
        lines.extend(["", "## Named References"])
        for ref in plan.named_references:
            ref_type_suffix = f" ({ref.reference_type})" if ref.reference_type != "file" else ""
            desc_suffix = f": {ref.description}" if ref.description else ""
            lines.append(f"- {ref.name}{ref_type_suffix}{desc_suffix}")
    return "\n".join(lines)
