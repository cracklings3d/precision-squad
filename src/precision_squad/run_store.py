"""Filesystem-backed run persistence."""

from __future__ import annotations

import json
from json import JSONDecodeError
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

APPROVED_PLAN_FILENAME = "approved-plan.json"
_ALLOWED_NAMED_REFERENCE_TYPES = {"file", "interface", "symbol", "example"}


class ApprovedPlanError(ValueError):
    """Base error for approved-plan artifact loading failures."""


class ApprovedPlanNotFoundError(ApprovedPlanError):
    """Raised when an approved-plan artifact is missing."""


class ApprovedPlanValidationError(ApprovedPlanError):
    """Raised when an approved-plan artifact fails canonical validation."""


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
        self._write_json(run_dir / APPROVED_PLAN_FILENAME, plan)

    @staticmethod
    def load_approved_plan(run_dir: Path, *, issue_ref: str) -> ApprovedPlan:
        return load_approved_plan_artifact(run_dir, issue_ref=issue_ref)

    @staticmethod
    def load_approved_plan_text(
        run_dir: Path,
        *,
        issue_ref: str,
        include_named_references: bool = False,
    ) -> str:
        """Load the approved plan and render it as markdown text."""
        plan = RunStore.load_approved_plan(run_dir, issue_ref=issue_ref)
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


def load_approved_plan_artifact(path: Path, *, issue_ref: str) -> ApprovedPlan:
    """Load and validate an approved-plan artifact from a file path or run directory."""
    plan_path = _resolve_approved_plan_path(path)
    if not plan_path.exists():
        raise ApprovedPlanNotFoundError(f"Approved plan artifact not found: {plan_path}")
    try:
        with plan_path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except JSONDecodeError as exc:
        raise ApprovedPlanValidationError(
            f"Approved plan artifact at {plan_path} is not valid JSON: {exc.msg}"
        ) from exc
    return _parse_approved_plan_payload(payload, path=plan_path, issue_ref=issue_ref)


def _resolve_approved_plan_path(path: Path) -> Path:
    if path.exists() and path.is_dir():
        return path / APPROVED_PLAN_FILENAME
    return path


def _parse_approved_plan_payload(
    payload: object,
    *,
    path: Path,
    issue_ref: str,
) -> ApprovedPlan:
    if not isinstance(payload, dict):
        raise ApprovedPlanValidationError(f"Expected JSON object in {path}")

    plan_issue_ref = _require_non_empty_str_field(payload, field_name="issue_ref")
    if plan_issue_ref != issue_ref:
        raise ApprovedPlanValidationError(
            f"Approved plan issue_ref '{plan_issue_ref}' does not match expected issue_ref '{issue_ref}'"
        )

    return ApprovedPlan(
        issue_ref=plan_issue_ref,
        plan_summary=_require_non_empty_str_field(payload, field_name="plan_summary"),
        implementation_steps=_read_implementation_steps(payload),
        named_references=_read_named_references(payload),
        retrieval_surface_summary=_require_string_field(
            payload,
            field_name="retrieval_surface_summary",
        ),
        approved=_read_approved_flag(payload),
    )


def _require_non_empty_str(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ApprovedPlanValidationError(f"Approved plan field '{field_name}' must be a string")
    if not value.strip():
        raise ApprovedPlanValidationError(f"Approved plan is missing a non-empty '{field_name}'")
    return value


def _require_non_empty_str_field(payload: dict[str, object], *, field_name: str) -> str:
    if field_name not in payload:
        raise ApprovedPlanValidationError(
            f"Approved plan is missing required field '{field_name}'"
        )
    return _require_non_empty_str(payload[field_name], field_name=field_name)


def _require_string_field(payload: dict[str, object], *, field_name: str) -> str:
    if field_name not in payload:
        raise ApprovedPlanValidationError(
            f"Approved plan is missing required field '{field_name}'"
        )
    value = payload[field_name]
    if not isinstance(value, str):
        raise ApprovedPlanValidationError(f"Approved plan field '{field_name}' must be a string")
    return value


def _read_implementation_steps(payload: dict[str, object]) -> tuple[str, ...]:
    if "implementation_steps" not in payload:
        raise ApprovedPlanValidationError(
            "Approved plan is missing required field 'implementation_steps'"
        )
    implementation_steps_raw = payload["implementation_steps"]
    if not isinstance(implementation_steps_raw, list):
        raise ApprovedPlanValidationError("Expected 'implementation_steps' to be a list")
    implementation_steps: list[str] = []
    for index, step in enumerate(implementation_steps_raw, start=1):
        if not isinstance(step, str):
            raise ApprovedPlanValidationError(
                f"Approved plan implementation_steps[{index}] must be a string"
            )
        if not step.strip():
            raise ApprovedPlanValidationError(
                f"Approved plan implementation_steps[{index}] must be a non-empty string"
            )
        implementation_steps.append(step)
    if not implementation_steps:
        raise ApprovedPlanValidationError("Approved plan has no implementation steps")
    return tuple(implementation_steps)


def _read_named_references(payload: dict[str, object]) -> tuple[NamedReference, ...]:
    if "named_references" not in payload:
        raise ApprovedPlanValidationError(
            "Approved plan is missing required field 'named_references'"
        )
    named_references_raw = payload["named_references"]
    if not isinstance(named_references_raw, list):
        raise ApprovedPlanValidationError("Expected 'named_references' to be a list")

    named_refs: list[NamedReference] = []
    for index, ref in enumerate(named_references_raw, start=1):
        if isinstance(ref, str):
            name = _require_non_empty_str(ref, field_name=f"named_references[{index}]")
            named_refs.append(NamedReference(name=name))
            continue
        if not isinstance(ref, dict):
            raise ApprovedPlanValidationError(
                f"Approved plan named_references[{index}] must be a string or object"
            )

        if "name" not in ref:
            raise ApprovedPlanValidationError(
                f"Approved plan named_references[{index}] is missing required field 'name'"
            )
        name = _require_non_empty_str(ref["name"], field_name=f"named_references[{index}].name")

        reference_type = ref.get("reference_type", "file")
        if not isinstance(reference_type, str) or reference_type not in _ALLOWED_NAMED_REFERENCE_TYPES:
            raise ApprovedPlanValidationError(
                "Approved plan named_references[{}].reference_type must be one of {}".format(
                    index,
                    sorted(_ALLOWED_NAMED_REFERENCE_TYPES),
                )
            )

        description = ref.get("description", "")
        if not isinstance(description, str):
            raise ApprovedPlanValidationError(
                f"Approved plan named_references[{index}].description must be a string"
            )

        named_refs.append(
            NamedReference(
                name=name,
                reference_type=cast(Literal["file", "interface", "symbol", "example"], reference_type),
                description=description,
            )
        )
    return tuple(named_refs)


def _read_approved_flag(payload: dict[str, object]) -> bool:
    if "approved" not in payload:
        raise ApprovedPlanValidationError("Approved plan is missing required field 'approved'")
    approved_raw = payload["approved"]
    if not isinstance(approved_raw, bool):
        raise ApprovedPlanValidationError("Approved plan field 'approved' must be a boolean")
    if not approved_raw:
        raise ApprovedPlanValidationError("Approved plan must have 'approved': true")
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
