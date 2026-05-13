"""Core data models for issue intake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class IssueReference:
    """A GitHub issue reference in owner/repo#number form."""

    owner: str
    repo: str
    number: int

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


@dataclass(frozen=True, slots=True)
class GitHubIssue:
    """Normalized issue data fetched from GitHub."""

    reference: IssueReference
    title: str
    body: str
    labels: tuple[str, ...]
    html_url: str
    comments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IssueAssessment:
    """Deterministic decision about whether an issue is runnable."""

    status: Literal["runnable", "blocked"]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IssueIntake:
    """Normalized issue intake artifact."""

    issue: GitHubIssue
    summary: str
    problem_statement: str
    assessment: IssueAssessment


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Operator request to run one issue through the control plane."""

    issue_ref: str
    runs_dir: str


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Persisted metadata for one local run."""

    run_id: str
    issue_ref: str
    status: Literal["intake_complete", "blocked", "runnable"]
    created_at: str
    updated_at: str
    run_dir: str
    attempt: int = 1

    def with_attempt(self, attempt: int) -> RunRecord:
        """Return a copy with a different attempt number."""
        return RunRecord(
            run_id=self.run_id,
            issue_ref=self.issue_ref,
            status=self.status,
            created_at=self.created_at,
            updated_at=self.updated_at,
            run_dir=self.run_dir,
            attempt=attempt,
        )


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Normalized executor output."""

    status: Literal[
        "pending", "blocked", "failed_infra", "missing_docs", "ambiguous_docs", "completed"
    ]
    executor_name: str
    summary: str
    detail_codes: tuple[str, ...]
    artifact_dir: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    quality: Literal["green", "improved", "degraded"] | None = None


@dataclass(frozen=True, slots=True)
class ExecutionContract:
    """Documented local setup and QA contract extracted for one run."""

    source_path: str | None
    setup_commands: tuple[str, ...]
    qa_command: str | None
    notes: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()
    manual_prerequisites: tuple[str, ...] = ()
    environment_assumptions: tuple[str, ...] = ()
    verification_gaps: tuple[str, ...] = ()
    findings: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Normalized evaluation output after execution."""

    status: Literal["success", "blocked", "failed_infra"]
    summary: str
    detail_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SideIssue:
    """A secondary issue discovered during repair that is unrelated to the primary issue."""

    title: str
    summary: str
    body: str
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairResult:
    """Normalized result for the post-synthesis repair stage."""

    status: Literal["not_configured", "blocked", "failed_infra", "completed", "escalated"]
    summary: str
    detail_codes: tuple[str, ...]
    workspace_path: str | None = None
    patch_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    side_issues: tuple[SideIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class QaResult:
    """Deterministic verification result for a repaired workspace."""

    status: Literal["passed", "failed", "unrunnable", "failed_infra", "not_run"]
    summary: str
    detail_codes: tuple[str, ...]
    command: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    phase: Literal["baseline", "repair", "final"] = "repair"
    quality: Literal["green", "improved", "degraded"] | None = None


@dataclass(frozen=True, slots=True)
class GovernanceVerdict:
    """Deterministic governance decision for a run."""

    status: Literal["approved", "blocked"]
    summary: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublishPlan:
    """Prepared publish output for GitHub-facing surfaces."""

    status: Literal["draft_pr", "issue_comment", "follow_up_issue"]
    title: str
    body: str
    reason_codes: tuple[str, ...]
    branch_name: str | None = None
    pull_request_url: str | None = None
    pull_number: int | None = None


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Result of applying or previewing a publish plan."""

    status: Literal["dry_run", "published"]
    target: Literal["draft_pr", "issue_comment", "follow_up_issue"]
    summary: str
    url: str | None
    branch_name: str | None = None
    pull_number: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewAgentResult:
    """Result from one post-publish review agent."""

    role: Literal["reviewer", "architect"]
    status: Literal["approved", "rejected", "failed_infra", "not_run"]
    summary: str
    feedback: tuple[str, ...] = ()
    stdout_path: str | None = None
    stderr_path: str | None = None
    transcript_path: str | None = None


@dataclass(frozen=True, slots=True)
class NamedReference:
    """A named reference (file path, interface, symbol, or example) from the approved plan."""

    name: str
    reference_type: Literal["file", "interface", "symbol", "example"] = "file"
    description: str = ""


@dataclass(frozen=True, slots=True)
class ApprovedPlan:
    """Canonical approved-plan artifact for downstream stage consumption."""

    issue_ref: str
    plan_summary: str
    implementation_steps: tuple[str, ...]
    named_references: tuple[NamedReference, ...]
    retrieval_surface_summary: str
    approved: bool = True


@dataclass(frozen=True, slots=True)
class PostPublishReviewResult:
    """Combined result for post-publish PR review."""

    status: Literal["approved", "rejected", "failed_infra", "not_run"]
    summary: str
    pull_request_url: str | None
    pull_number: int | None
    reviewer_status: Literal["approved", "rejected", "failed_infra", "not_run"]
    reviewer_summary: str
    pull_head_sha: str | None = None
    reviewer_feedback: tuple[str, ...] = ()
    architect_status: Literal["approved", "rejected", "failed_infra", "not_run"] = "not_run"
    architect_summary: str = "Architect review did not run."
    architect_feedback: tuple[str, ...] = ()
    issue_comment_url: str | None = None
    issue_reopened: bool = False
