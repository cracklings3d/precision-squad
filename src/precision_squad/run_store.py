"""Filesystem-backed run persistence."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from .intake import canonicalize_local_issue_ref, derive_issue_draft
from .models import (
    ApprovedPlan,
    DecisionLogArtifact,
    DesignDecision,
    EvaluationResult,
    ExecutionResult,
    GovernanceVerdict,
    ImplReviewFeedback,
    ImplReviewResult,
    IssueDraft,
    IssueDraftProvenance,
    IssueIntake,
    IssueReview,
    IssueReviewFeedback,
    IssueReviewProvenance,
    NamedReference,
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

PersistedArtifact = (
    ApprovedPlan
    | DecisionLogArtifact
    | EvaluationResult
    | ExecutionResult
    | GovernanceVerdict
    | ImplReviewResult
    | IssueDraft
    | IssueIntake
    | IssueReview
    | PlanReview
    | PostPublishReviewResult
    | PublishPlan
    | PublishResult
    | QaResult
    | RepairResult
    | RunRecord
    | RunRequest
)

APPROVED_PLAN_FILENAME = "approved-plan.json"
DECISION_LOG_FILENAME_TEMPLATE = "decision-log.attempt-{attempt}.json"
IMPL_REVIEW_FILENAME = "impl-review.json"
ISSUE_REVIEW_FILENAME = "issue-review.json"
PLAN_REVIEW_FILENAME = "plan-review.json"
_ALLOWED_NAMED_REFERENCE_TYPES = {"file", "interface", "symbol", "example"}


class ApprovedPlanError(ValueError):
    """Base error for approved-plan artifact loading failures."""


class ApprovedPlanNotFoundError(ApprovedPlanError):
    """Raised when an approved-plan artifact is missing."""


class ApprovedPlanValidationError(ApprovedPlanError):
    """Raised when an approved-plan artifact fails canonical validation."""


class IssueReviewError(ValueError):
    """Base error for issue-review artifact loading or gate failures."""


class IssueReviewNotFoundError(IssueReviewError):
    """Raised when an issue-review artifact is missing."""


class IssueReviewValidationError(IssueReviewError):
    """Raised when an issue-review artifact fails canonical validation."""


class ApprovedPlanGateError(ValueError):
    """Raised when approved-plan persistence is attempted without review approval."""


class PlanReviewError(ValueError):
    """Base error for plan-review artifact loading or gate failures."""


class PlanReviewNotFoundError(PlanReviewError):
    """Raised when a plan-review artifact is missing."""


class PlanReviewValidationError(PlanReviewError):
    """Raised when a plan-review artifact fails canonical validation."""


class PlanReviewNotApprovedError(PlanReviewError):
    """Raised when a valid plan-review artifact is not approved for implement ingress."""


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
        issue_draft = derive_issue_draft(request, intake)

        self._write_json(run_dir / "run-request.json", request)
        self._write_json(run_dir / "issue-intake.json", intake)
        self._write_json(run_dir / "issue-draft.json", issue_draft)
        self._write_issue_context(run_dir / "issue.md", intake)
        self._write_json(run_dir / "run-record.json", record)
        return record

    def create_retry_run(
        self,
        request: RunRequest,
        *,
        source_run_dir: Path,
        preserved_intake: IssueIntake,
        attempt: int,
    ) -> RunRecord:
        created_at = _utc_now()
        run_id = _build_run_id(created_at)
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        status = "blocked" if preserved_intake.assessment.status == "blocked" else "runnable"
        record = RunRecord(
            run_id=run_id,
            issue_ref=request.issue_ref,
            status=status,
            created_at=created_at,
            updated_at=created_at,
            run_dir=str(run_dir),
            attempt=attempt,
        )

        shutil.copy2(source_run_dir / "issue-intake.json", run_dir / "issue-intake.json")
        self._write_json(run_dir / "run-request.json", request)
        self._write_issue_context(run_dir / "issue.md", preserved_intake)
        self._write_json(run_dir / "run-record.json", record)
        return record

    def copy_retry_artifacts(
        self,
        *,
        source_run_dir: Path,
        target_run_dir: Path,
        artifact_names: tuple[str, ...],
        target_run_id: str | None = None,
        source_attempt: int | None = None,
        target_attempt: int | None = None,
        copy_repair_workspace: bool = False,
    ) -> None:
        for artifact_name in artifact_names:
            source_path = source_run_dir / artifact_name
            target_path = target_run_dir / artifact_name
            if not source_path.exists():
                continue
            shutil.copy2(source_path, target_path)
            if (
                target_run_id is not None
                and artifact_name in {ISSUE_REVIEW_FILENAME, PLAN_REVIEW_FILENAME}
            ):
                self._rewrite_review_run_id(target_path, target_run_id)

        if source_attempt is not None and target_attempt is not None:
            source_decision_log = source_run_dir / _decision_log_filename(source_attempt)
            if source_decision_log.exists():
                target_decision_log = target_run_dir / _decision_log_filename(target_attempt)
                shutil.copy2(source_decision_log, target_decision_log)
                self._rewrite_decision_log_attempt(target_decision_log, target_attempt)

        if copy_repair_workspace:
            source_workspace = source_run_dir / "repair-workspace"
            target_workspace = target_run_dir / "repair-workspace"
            if source_workspace.is_dir():
                shutil.copytree(source_workspace, target_workspace)
                repair_result_path = target_run_dir / "repair-result.json"
                if repair_result_path.exists():
                    self._rewrite_repair_result_workspace_path(
                        repair_result_path,
                        workspace_path=str(target_workspace.resolve()),
                    )

    @staticmethod
    def _rewrite_review_run_id(path: Path, run_id: str) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["run_id"] = run_id
            provenance = payload.get("provenance")
            if isinstance(provenance, dict):
                provenance["run_id"] = run_id
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _rewrite_decision_log_attempt(path: Path, attempt: int) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["attempt"] = attempt
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _rewrite_repair_result_workspace_path(path: Path, workspace_path: str) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["workspace_path"] = workspace_path
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def load_issue_draft(self, run_id: str) -> IssueDraft:
        """Load the normalized issue handoff artifact for a run."""
        run_dir = self.root / run_id
        return self.load_issue_draft_from_dir(run_dir)

    @staticmethod
    def load_issue_draft_from_dir(run_dir: Path) -> IssueDraft:
        """Load the normalized issue handoff artifact from a run directory."""
        path = run_dir / "issue-draft.json"
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        return _parse_issue_draft_payload(payload)

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

    def list_runs_for_issue(self, issue_ref: str) -> list[RunRecord]:
        """Return prior local runs for one canonical issue, newest first."""
        if not self.root.exists():
            return []

        canonical_issue_ref = canonicalize_local_issue_ref(issue_ref)
        matches: list[RunRecord] = []
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            record_path = child / "run-record.json"
            if not record_path.exists():
                continue
            try:
                record = _read_run_record(record_path)
            except (OSError, ValueError, JSONDecodeError, KeyError, TypeError):
                continue
            if canonicalize_local_issue_ref(record.issue_ref) == canonical_issue_ref:
                matches.append(record)

        matches.sort(key=lambda record: record.run_id)
        matches.sort(key=lambda record: record.created_at, reverse=True)
        return matches

    def write_execution_result(self, run_dir: Path, result: ExecutionResult) -> None:
        self._write_json(run_dir / "execution-result.json", result)

    def write_approved_plan(self, run_dir: Path, plan: ApprovedPlan) -> None:
        self._write_json(run_dir / APPROVED_PLAN_FILENAME, plan)

    def write_gated_approved_plan(
        self,
        run_dir: Path,
        plan: ApprovedPlan,
        *,
        expected_run_id: str | None = None,
    ) -> None:
        self.require_issue_review_approval(
            run_dir,
            issue_ref=plan.issue_ref,
            expected_run_id=expected_run_id,
        )
        self._write_json(run_dir / APPROVED_PLAN_FILENAME, plan)

    def write_issue_review(self, run_dir: Path, review: IssueReview) -> None:
        self._write_json(run_dir / ISSUE_REVIEW_FILENAME, review)

    def write_plan_review(self, run_dir: Path, review: PlanReview) -> None:
        self._write_json(run_dir / PLAN_REVIEW_FILENAME, review)

    def write_impl_review(self, run_dir: Path, review: ImplReviewResult) -> None:
        self._write_json(run_dir / IMPL_REVIEW_FILENAME, review)

    @staticmethod
    def load_impl_review(run_dir: Path) -> ImplReviewResult:
        path = run_dir / IMPL_REVIEW_FILENAME
        if not path.exists():
            raise ValueError(f"Implementation review artifact not found: {path}")
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        return _parse_impl_review_payload(payload, path=path)

    @staticmethod
    def load_issue_review(
        run_dir: Path,
        *,
        issue_ref: str,
        expected_run_id: str | None = None,
    ) -> IssueReview:
        path = run_dir / ISSUE_REVIEW_FILENAME
        if not path.exists():
            raise IssueReviewNotFoundError(f"Issue review artifact not found: {path}")
        try:
            with path.open(encoding="utf-8") as f:
                payload = json.load(f)
        except JSONDecodeError as exc:
            raise IssueReviewValidationError(
                f"Issue review artifact at {path} is not valid JSON: {exc.msg}"
            ) from exc
        return _parse_issue_review_payload(
            payload,
            path=path,
            issue_ref=issue_ref,
            expected_run_id=expected_run_id,
        )

    @staticmethod
    def require_issue_review_approval(
        run_dir: Path,
        *,
        issue_ref: str,
        expected_run_id: str | None = None,
    ) -> IssueReview:
        try:
            review = RunStore.load_issue_review(
                run_dir,
                issue_ref=issue_ref,
                expected_run_id=expected_run_id,
            )
        except IssueReviewNotFoundError as exc:
            raise ApprovedPlanGateError(
                f"Approved plan persistence requires issue-review.json for {issue_ref}."
            ) from exc
        if review.review_status != "approved":
            raise ApprovedPlanGateError(
                "Approved plan persistence requires issue-review.json.review_status to be "
                f"'approved'; found '{review.review_status}' for {issue_ref}."
            )
        return review

    @staticmethod
    def load_plan_review(
        run_dir: Path,
        *,
        issue_ref: str,
        expected_run_id: str | None = None,
    ) -> PlanReview:
        path = run_dir / PLAN_REVIEW_FILENAME
        if not path.exists():
            raise PlanReviewNotFoundError(f"Plan review artifact not found: {path}")
        try:
            with path.open(encoding="utf-8") as f:
                payload = json.load(f)
        except JSONDecodeError as exc:
            raise PlanReviewValidationError(
                f"Plan review artifact at {path} is not valid JSON: {exc.msg}"
            ) from exc
        return _parse_plan_review_payload(
            payload,
            path=path,
            issue_ref=issue_ref,
            expected_run_id=expected_run_id,
        )

    @staticmethod
    def require_plan_review_for_implement(run_dir: Path, *, issue_ref: str) -> PlanReview:
        record_path = run_dir / "run-record.json"
        try:
            record = _read_run_record(record_path)
        except FileNotFoundError as exc:
            raise PlanReviewValidationError(
                f"Implement ingress requires a valid run-record.json at {record_path}."
            ) from exc
        except JSONDecodeError as exc:
            raise PlanReviewValidationError(
                "Implement ingress requires run-record.json at "
                f"{record_path} to be valid JSON: {exc.msg}"
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanReviewValidationError(
                f"Implement ingress requires run-record.json at {record_path} to be valid: {exc}"
            ) from exc
        review = RunStore.load_plan_review(
            run_dir,
            issue_ref=issue_ref,
            expected_run_id=record.run_id,
        )
        if review.review_status != "approved":
            raise PlanReviewNotApprovedError(
                "Implement ingress requires plan-review.json.review_status to be 'approved'; "
                f"found '{review.review_status}' for {issue_ref}."
            )
        return review

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

    def write_decision_log(self, run_dir: Path, artifact: DecisionLogArtifact) -> None:
        self._write_json(run_dir / _decision_log_filename(artifact.attempt), artifact)

    @staticmethod
    def load_decision_log(run_dir: Path, *, attempt: int) -> DecisionLogArtifact:
        path = run_dir / _decision_log_filename(attempt)
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        return _parse_decision_log_payload(payload)

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


def _parse_issue_draft_payload(payload: object) -> IssueDraft:
    if not isinstance(payload, dict):
        raise ValueError("Issue draft payload must be a JSON object")

    provenance_raw = payload.get("provenance")
    if not isinstance(provenance_raw, dict):
        raise ValueError("Issue draft field 'provenance' must be an object")

    source_artifacts = provenance_raw.get("source_artifacts")
    if not isinstance(source_artifacts, list) or not all(
        isinstance(item, str) for item in source_artifacts
    ):
        raise ValueError("Issue draft provenance.source_artifacts must be a list of strings")

    requested_issue_ref = provenance_raw.get("requested_issue_ref")
    if not isinstance(requested_issue_ref, str):
        raise ValueError("Issue draft provenance.requested_issue_ref must be a string")

    intake_status = payload.get("intake_status")
    if intake_status not in {"runnable", "blocked"}:
        raise ValueError("Issue draft field 'intake_status' must be 'runnable' or 'blocked'")

    intake_reason_codes = payload.get("intake_reason_codes")
    if not isinstance(intake_reason_codes, list) or not all(
        isinstance(item, str) for item in intake_reason_codes
    ):
        raise ValueError("Issue draft field 'intake_reason_codes' must be a list of strings")

    labels = payload.get("labels")
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("Issue draft field 'labels' must be a list of strings")

    owner = payload.get("owner")
    repo = payload.get("repo")
    number = payload.get("number")
    issue_ref = payload.get("issue_ref")
    issue_url = payload.get("issue_url")
    title = payload.get("title")
    summary = payload.get("summary")
    problem_statement = payload.get("problem_statement")
    if not isinstance(owner, str):
        raise ValueError("Issue draft field 'owner' must be a string")
    if not isinstance(repo, str):
        raise ValueError("Issue draft field 'repo' must be a string")
    if not isinstance(number, int):
        raise ValueError("Issue draft field 'number' must be an integer")
    if not isinstance(issue_ref, str):
        raise ValueError("Issue draft field 'issue_ref' must be a string")
    if not isinstance(issue_url, str):
        raise ValueError("Issue draft field 'issue_url' must be a string")
    if not isinstance(title, str):
        raise ValueError("Issue draft field 'title' must be a string")
    if not isinstance(summary, str):
        raise ValueError("Issue draft field 'summary' must be a string")
    if not isinstance(problem_statement, str):
        raise ValueError("Issue draft field 'problem_statement' must be a string")

    return IssueDraft(
        owner=owner,
        repo=repo,
        number=number,
        issue_ref=issue_ref,
        issue_url=issue_url,
        title=title,
        summary=summary,
        problem_statement=problem_statement,
        labels=tuple(labels),
        intake_status=cast(Literal["runnable", "blocked"], intake_status),
        intake_reason_codes=tuple(intake_reason_codes),
        provenance=IssueDraftProvenance(
            source_artifacts=tuple(source_artifacts),
            requested_issue_ref=requested_issue_ref,
        ),
    )


def _parse_issue_review_payload(
    payload: object,
    *,
    path: Path,
    issue_ref: str,
    expected_run_id: str | None,
) -> IssueReview:
    if not isinstance(payload, dict):
        raise IssueReviewValidationError(f"Expected JSON object in {path}")

    review_issue_ref = payload.get("issue_ref")
    if not isinstance(review_issue_ref, str):
        raise IssueReviewValidationError("Issue review field 'issue_ref' must be a string")
    if review_issue_ref != issue_ref:
        raise IssueReviewValidationError(
            "Issue review issue_ref "
            f"'{review_issue_ref}' does not match expected issue_ref '{issue_ref}'"
        )

    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise IssueReviewValidationError("Issue review field 'run_id' must be a non-empty string")
    if expected_run_id is not None and run_id != expected_run_id:
        raise IssueReviewValidationError(
            "Issue review run_id "
            f"'{run_id}' does not match expected run_id '{expected_run_id}'"
        )

    review_status = payload.get("review_status")
    if review_status not in {"approved", "changes_requested", "blocked"}:
        raise IssueReviewValidationError(
            "Issue review field 'review_status' must be 'approved', "
            "'changes_requested', or 'blocked'"
        )

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise IssueReviewValidationError("Issue review field 'summary' must be a non-empty string")

    feedback_raw = payload.get("feedback")
    if not isinstance(feedback_raw, list):
        raise IssueReviewValidationError("Issue review field 'feedback' must be a list")
    feedback: list[IssueReviewFeedback] = []
    for index, item in enumerate(feedback_raw, start=1):
        if not isinstance(item, dict):
            raise IssueReviewValidationError(f"Issue review feedback[{index}] must be an object")
        code = item.get("code")
        message = item.get("message")
        artifact = item.get("artifact")
        field = item.get("field")
        if not isinstance(code, str) or not code.strip():
            raise IssueReviewValidationError(
                f"Issue review feedback[{index}].code must be a non-empty string"
            )
        if not isinstance(message, str) or not message.strip():
            raise IssueReviewValidationError(
                f"Issue review feedback[{index}].message must be a non-empty string"
            )
        if not isinstance(artifact, str) or not artifact.strip():
            raise IssueReviewValidationError(
                f"Issue review feedback[{index}].artifact must be a non-empty string"
            )
        if not isinstance(field, str):
            raise IssueReviewValidationError(
                f"Issue review feedback[{index}].field must be a string"
            )
        feedback.append(
            IssueReviewFeedback(code=code, message=message, artifact=artifact, field=field)
        )

    provenance_raw = payload.get("provenance")
    if not isinstance(provenance_raw, dict):
        raise IssueReviewValidationError("Issue review field 'provenance' must be an object")
    source_artifact = provenance_raw.get("source_artifact")
    provenance_run_id = provenance_raw.get("run_id")
    provenance_issue_ref = provenance_raw.get("issue_ref")
    if source_artifact != "issue-draft.json":
        raise IssueReviewValidationError(
            "Issue review provenance.source_artifact must be exactly 'issue-draft.json'"
        )
    if not isinstance(provenance_run_id, str) or provenance_run_id != run_id:
        raise IssueReviewValidationError(
            "Issue review provenance.run_id must match issue review run_id"
        )
    if not isinstance(provenance_issue_ref, str) or provenance_issue_ref != review_issue_ref:
        raise IssueReviewValidationError(
            "Issue review provenance.issue_ref must match issue review issue_ref"
        )

    return IssueReview(
        run_id=run_id,
        issue_ref=review_issue_ref,
        review_status=cast(Literal["approved", "changes_requested", "blocked"], review_status),
        summary=summary,
        feedback=tuple(feedback),
        provenance=IssueReviewProvenance(
            source_artifact=source_artifact,
            run_id=provenance_run_id,
            issue_ref=provenance_issue_ref,
        ),
    )


def _parse_plan_review_payload(
    payload: object,
    *,
    path: Path,
    issue_ref: str,
    expected_run_id: str | None,
) -> PlanReview:
    if not isinstance(payload, dict):
        raise PlanReviewValidationError(f"Expected JSON object in {path}")

    review_issue_ref = payload.get("issue_ref")
    if not isinstance(review_issue_ref, str):
        raise PlanReviewValidationError("Plan review field 'issue_ref' must be a string")
    if review_issue_ref != issue_ref:
        raise PlanReviewValidationError(
            "Plan review issue_ref "
            f"'{review_issue_ref}' does not match expected issue_ref '{issue_ref}'"
        )

    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise PlanReviewValidationError("Plan review field 'run_id' must be a non-empty string")
    if expected_run_id is not None and run_id != expected_run_id:
        raise PlanReviewValidationError(
            f"Plan review run_id '{run_id}' does not match expected run_id '{expected_run_id}'"
        )

    review_status = payload.get("review_status")
    if review_status not in {"approved", "changes_requested", "blocked"}:
        raise PlanReviewValidationError(
            "Plan review field 'review_status' must be 'approved', "
            "'changes_requested', or 'blocked'"
        )

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise PlanReviewValidationError("Plan review field 'summary' must be a non-empty string")

    feedback_raw = payload.get("feedback")
    if not isinstance(feedback_raw, list):
        raise PlanReviewValidationError("Plan review field 'feedback' must be a list")
    feedback: list[PlanReviewFeedback] = []
    for index, item in enumerate(feedback_raw, start=1):
        if not isinstance(item, dict):
            raise PlanReviewValidationError(f"Plan review feedback[{index}] must be an object")
        code = item.get("code")
        message = item.get("message")
        artifact = item.get("artifact")
        field = item.get("field")
        if not isinstance(code, str) or not code.strip():
            raise PlanReviewValidationError(
                f"Plan review feedback[{index}].code must be a non-empty string"
            )
        if not isinstance(message, str) or not message.strip():
            raise PlanReviewValidationError(
                f"Plan review feedback[{index}].message must be a non-empty string"
            )
        if not isinstance(artifact, str) or not artifact.strip():
            raise PlanReviewValidationError(
                f"Plan review feedback[{index}].artifact must be a non-empty string"
            )
        if not isinstance(field, str):
            raise PlanReviewValidationError(
                f"Plan review feedback[{index}].field must be a string"
            )
        feedback.append(
            PlanReviewFeedback(code=code, message=message, artifact=artifact, field=field)
        )

    provenance_raw = payload.get("provenance")
    if not isinstance(provenance_raw, dict):
        raise PlanReviewValidationError("Plan review field 'provenance' must be an object")
    source_artifact = provenance_raw.get("source_artifact")
    provenance_run_id = provenance_raw.get("run_id")
    provenance_issue_ref = provenance_raw.get("issue_ref")
    if source_artifact != APPROVED_PLAN_FILENAME:
        raise PlanReviewValidationError(
            f"Plan review provenance.source_artifact must be exactly '{APPROVED_PLAN_FILENAME}'"
        )
    if not isinstance(provenance_run_id, str) or provenance_run_id != run_id:
        raise PlanReviewValidationError(
            "Plan review provenance.run_id must match plan review run_id"
        )
    if not isinstance(provenance_issue_ref, str) or provenance_issue_ref != review_issue_ref:
        raise PlanReviewValidationError(
            "Plan review provenance.issue_ref must match plan review issue_ref"
        )

    return PlanReview(
        run_id=run_id,
        issue_ref=review_issue_ref,
        review_status=cast(Literal["approved", "changes_requested", "blocked"], review_status),
        summary=summary,
        feedback=tuple(feedback),
        provenance=PlanReviewProvenance(
            source_artifact=cast(str, source_artifact),
            run_id=provenance_run_id,
            issue_ref=provenance_issue_ref,
        ),
    )


def _parse_impl_review_payload(payload: object, *, path: Path) -> ImplReviewResult:
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")

    review_status = payload.get("review_status")
    if review_status not in {"approved", "changes_requested", "blocked"}:
        raise ValueError(
            "Implementation review field 'review_status' must be 'approved', "
            "'changes_requested', or 'blocked'"
        )

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Implementation review field 'summary' must be a non-empty string")

    feedback_raw = payload.get("feedback")
    if not isinstance(feedback_raw, list):
        raise ValueError("Implementation review field 'feedback' must be a list")
    feedback: list[ImplReviewFeedback] = []
    for index, item in enumerate(feedback_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Implementation review feedback[{index}] must be an object")
        code = item.get("code")
        message = item.get("message")
        source = item.get("source")
        if not isinstance(code, str) or not code.strip():
            raise ValueError(
                f"Implementation review feedback[{index}].code must be a non-empty string"
            )
        if not isinstance(message, str) or not message.strip():
            raise ValueError(
                f"Implementation review feedback[{index}].message must be a non-empty string"
            )
        if source not in {"stage", "reviewer", "architect"}:
            raise ValueError(
                "Implementation review feedback[{}].source must be 'stage', 'reviewer', or "
                "'architect'".format(index)
            )
        feedback.append(
            ImplReviewFeedback(
                code=code,
                message=message,
                source=cast(Literal["stage", "reviewer", "architect"], source),
            )
        )

    return ImplReviewResult(
        review_status=cast(Literal["approved", "changes_requested", "blocked"], review_status),
        summary=summary,
        pull_request_url=cast(str | None, payload.get("pull_request_url")),
        pull_number=cast(int | None, payload.get("pull_number")),
        pull_head_sha=cast(str | None, payload.get("pull_head_sha")),
        feedback=tuple(feedback),
        reviewer_status=cast(
            Literal["approved", "rejected", "failed_infra", "not_run"],
            payload.get("reviewer_status", "not_run"),
        ),
        reviewer_summary=cast(str, payload.get("reviewer_summary", "Reviewer review did not run.")),
        architect_status=cast(
            Literal["approved", "rejected", "failed_infra", "not_run"],
            payload.get("architect_status", "not_run"),
        ),
        architect_summary=cast(
            str, payload.get("architect_summary", "Architect review did not run.")
        ),
        issue_comment_url=cast(str | None, payload.get("issue_comment_url")),
        issue_reopened=bool(payload.get("issue_reopened", False)),
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
            "Approved plan issue_ref "
            f"'{plan_issue_ref}' does not match expected issue_ref '{issue_ref}'"
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
        if (
            not isinstance(reference_type, str)
            or reference_type not in _ALLOWED_NAMED_REFERENCE_TYPES
        ):
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
                reference_type=cast(
                    Literal["file", "interface", "symbol", "example"],
                    reference_type,
                ),
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


def _decision_log_filename(attempt: int) -> str:
    return DECISION_LOG_FILENAME_TEMPLATE.format(attempt=attempt)


def _parse_decision_log_payload(payload: object) -> DecisionLogArtifact:
    if not isinstance(payload, dict):
        raise ValueError("Decision log payload must be a JSON object")

    attempt = payload.get("attempt")
    entries_raw = payload.get("entries")
    if not isinstance(attempt, int):
        raise ValueError("Decision log field 'attempt' must be an integer")
    if not isinstance(entries_raw, list):
        raise ValueError("Decision log field 'entries' must be a list")

    entries: list[DesignDecision] = []
    for index, item in enumerate(entries_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Decision log entries[{index}] must be an object")
        sequence = item.get("sequence")
        summary = item.get("summary")
        rationale = item.get("rationale")
        plan_steps = _read_decision_log_string_list(item, field_name="plan_steps", index=index)
        named_references = _read_decision_log_string_list(
            item,
            field_name="named_references",
            index=index,
        )
        affected_targets = _read_decision_log_string_list(
            item,
            field_name="affected_targets",
            index=index,
        )
        if not isinstance(sequence, int):
            raise ValueError(f"Decision log entries[{index}].sequence must be an integer")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"Decision log entries[{index}].summary must be a non-empty string")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(
                f"Decision log entries[{index}].rationale must be a non-empty string"
            )
        entries.append(
            DesignDecision(
                sequence=sequence,
                summary=summary,
                rationale=rationale,
                plan_steps=plan_steps,
                named_references=named_references,
                affected_targets=affected_targets,
            )
        )
    return DecisionLogArtifact(attempt=attempt, entries=tuple(entries))


def _read_decision_log_string_list(
    payload: dict[str, object], *, field_name: str, index: int
) -> tuple[str, ...]:
    raw = payload.get(field_name, [])
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"Decision log entries[{index}].{field_name} must be a list of strings")
    return tuple(raw)
