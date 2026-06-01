"""Prepare GitHub-facing publish plans."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .docs_remediation import (
    DOCS_REMEDIATION_MARKER,
    docs_baseline_findings_marker,
    docs_blocker_findings_marker,
    docs_blocker_fingerprint,
    docs_blocker_fingerprint_marker,
    docs_target_findings_marker,
    extract_docs_baseline_findings,
    extract_docs_target_findings,
    load_contract_findings,
    normalize_docs_findings,
)
from .github_client import GitHubClientError, GitHubWriteClient
from .intake import is_docs_remediation_issue
from .models import (
    GovernanceVerdict,
    IssueIntake,
    IssueReference,
    PostPublishReviewResult,
    PublishPlan,
    RepairResult,
    RunRecord,
)
from .rerun_context import latest_rejected_pull_request
from .run_store import RunStore

logger = logging.getLogger(__name__)


class RequiredDecisionLogArtifactMissingError(ValueError):
    """Raised when a completed repair attempt is missing its required decision-log artifact."""


@dataclass(frozen=True, slots=True)
class PostReviewAutomationResult:
    """Result of post-review GitHub automation."""

    status: Literal["success", "failed", "skipped"]
    summary: str
    operations_completed: tuple[str, ...]
    error: str | None = None


def build_publish_plan(
    intake: IssueIntake,
    run_record: RunRecord,
    verdict: GovernanceVerdict,
    repair_result: RepairResult | None = None,
) -> PublishPlan:
    """Prepare the first publish plan without calling GitHub yet."""
    if verdict.verdict == "approved":
        context_heading = "## Summary\n"
        context_note = ""
        rejected_pr = latest_rejected_pull_request(intake.issue.comments)
        return PublishPlan(
            status="draft_pr",
            title=intake.summary,
            body=(
                context_heading
                + f"- Run ID: `{run_record.run_id}`\n"
                + f"- Issue: `{intake.issue.reference}`\n"
                + f"- Governance verdict: `{verdict.verdict}`\n"
                + context_note
                + _render_design_decisions_section(
                    run_record,
                    require_artifact=(
                        repair_result is not None and repair_result.status == "completed"
                    ),
                )
            ),
            reason_codes=verdict.reason_codes,
            pull_request_url=rejected_pr.url if rejected_pr else None,
            pull_number=rejected_pr.number if rejected_pr else None,
        )

    if _should_create_follow_up_issue(intake, verdict):
        reason_lines = "\n".join(f"- {code}" for code in verdict.reason_codes)
        target_findings, baseline_findings = _findings_for_follow_up_issue(
            intake,
            run_record,
            verdict,
        )
        fingerprint = docs_blocker_fingerprint(target_findings)
        return PublishPlan(
            status="follow_up_issue",
            title=(
                "Docs blocker surfaced while repairing "
                f"#{intake.issue.reference.number}: clarify deterministic setup and QA"
            ),
            body=(
                f"{DOCS_REMEDIATION_MARKER}\n"
                f"{docs_blocker_fingerprint_marker(fingerprint)}\n"
                f"{docs_blocker_findings_marker(target_findings)}\n"
                f"{docs_target_findings_marker(target_findings)}\n"
                f"{docs_baseline_findings_marker(baseline_findings)}\n\n"
                "## Context\n"
                f"- Surfaced while repairing: `{intake.issue.reference}`\n"
                f"- Source issue URL: {intake.issue.html_url}\n"
                f"- Requested change: {intake.summary}\n"
                f"- Run ID: `{run_record.run_id}`\n"
                "\n"
                "## Why This Is Separate\n"
                "This run was blocked by repository-level documentation or environment "
                "uncertainty rather than by the requested feature change. Tracking it as "
                "a separate issue keeps the source issue focused on the original fix.\n"
                "\n"
                "## Blocker\n"
                f"{verdict.summary}\n"
                "\n"
                "## Reason Codes\n"
                f"{reason_lines}\n"
                "\n"
                "## Desired Outcome\n"
                "- document one canonical local setup path\n"
                "- document one canonical QA command\n"
                "- make prerequisites and environment assumptions explicit and verifiable\n"
            ),
            reason_codes=verdict.reason_codes,
        )

    if verdict.verdict == "blocked":
        side_issues = repair_result.side_issues if repair_result else ()
        if side_issues:
            side_issues_lines = []
            for si in side_issues:
                labels_str = (
                    ", ".join(f"`{label}`" for label in si.labels)
                    if si.labels
                    else "no labels"
                )
                side_issues_lines.append(
                    f"### {si.title}\n"
                    f"**Labels:** {labels_str}\n\n"
                    f"{si.summary}\n"
                )
            side_issues_body = "\n---\n\n".join(side_issues_lines)
            return PublishPlan(
                status="follow_up_issue",
                title=f"Side issues surfaced while repairing #{intake.issue.reference.number}",
                body=(
                    f"## Side Issues Surfaced\n"
                    f"- Surfaced while repairing: `{intake.issue.reference}`\n"
                    f"- Source issue URL: {intake.issue.html_url}\n"
                    f"- Requested change: {intake.summary}\n"
                    f"- Run ID: `{run_record.run_id}`\n"
                    f"- Governance verdict: `{verdict.verdict}`\n"
                    f"- Summary: {verdict.summary}\n"
                    "\n"
                    "## Side Issues\n"
                    f"{side_issues_body}\n"
                ),
                reason_codes=verdict.reason_codes,
            )

    reason_lines = "\n".join(f"- {code}" for code in verdict.reason_codes) or "- blocked"
    return PublishPlan(
        status="issue_comment",
        title=f"Blocked: {intake.summary}",
        body=(
            "## Blocked\n"
            f"- Run ID: `{run_record.run_id}`\n"
            f"- Issue: `{intake.issue.reference}`\n"
            f"- Verdict: `{verdict.verdict}`\n"
            f"- Summary: {verdict.summary}\n"
            "\n"
            "## Reasons\n"
            f"{reason_lines}\n"
        ),
        reason_codes=verdict.reason_codes,
    )


def _should_create_follow_up_issue(
    intake: IssueIntake, verdict: GovernanceVerdict
) -> bool:
    return (
        verdict.verdict == "blocked"
        and not is_docs_remediation_issue(intake)
        and intake.assessment.status == "runnable"
        and bool(verdict.reason_codes)
        and all(code.startswith("docs_") for code in verdict.reason_codes)
    )


def _findings_for_follow_up_issue(
    intake: IssueIntake,
    run_record: RunRecord,
    verdict: GovernanceVerdict,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    detail_codes = set(verdict.reason_codes)
    findings = load_contract_findings(Path(run_record.run_dir) / "execution-contract")
    if findings:
        matched = [
            finding
            for finding in findings
            if _finding_matches_reason_codes(finding, detail_codes)
        ]
        if matched:
            return normalize_docs_findings(matched), _baseline_findings_for_issue_comments(
                intake.issue.comments,
                normalize_docs_findings(matched),
            )

    fallback = normalize_docs_findings(
        [
            {
                "rule_id": code,
                "source_path": "repository-docs",
                "section_key": "docs",
                "subject_key": "docs-blocker",
            }
            for code in verdict.reason_codes
        ]
    )
    return fallback, _baseline_findings_for_issue_comments(intake.issue.comments, fallback)


def _baseline_findings_for_issue_comments(
    comments: tuple[str, ...],
    target_findings: list[dict[str, str]],
) -> list[dict[str, str]]:
    baseline: list[dict[str, str]] = []
    for comment in comments:
        baseline.extend(extract_docs_target_findings(comment))
        baseline.extend(extract_docs_baseline_findings(comment))
    return normalize_docs_findings(
        [finding for finding in baseline if finding not in target_findings]
    )


def _finding_matches_reason_codes(
    finding: dict[str, str], reason_codes: set[str]
) -> bool:
    rule_id = finding.get("rule_id", "")
    if rule_id in reason_codes:
        return True

    umbrella_mapping = {
        "docs_setup_prerequisites_ambiguous": {
            "docs_setup_prerequisite_manual_only",
            "docs_setup_prerequisite_version_pinned",
            "docs_setup_prerequisite_source_unambiguous",
            "docs_setup_prerequisite_verification_present",
            "docs_environment_assumptions_explicit",
            "docs_environment_mutation_verification_present",
        },
        "docs_contract_incomplete": {
            "docs_setup_command_present",
            "docs_qa_command_present",
            "docs_commands_explained",
        },
    }
    return any(
        code in reason_codes and rule_id in mapped_rule_ids
        for code, mapped_rule_ids in umbrella_mapping.items()
    )


def _render_design_decisions_section(
    run_record: RunRecord, *, require_artifact: bool = False
) -> str:
    try:
        artifact = RunStore.load_decision_log(Path(run_record.run_dir), attempt=run_record.attempt)
    except FileNotFoundError as exc:
        if not require_artifact:
            return ""
        raise RequiredDecisionLogArtifactMissingError(
            "Missing required decision-log artifact for "
            f"run {run_record.run_id} attempt {run_record.attempt}: {exc.filename}"
        ) from exc
    if not artifact.entries:
        return ""

    payload = [
        {
            "sequence": entry.sequence,
            "summary": entry.summary,
            "rationale": entry.rationale,
            "plan_steps": list(entry.plan_steps),
            "named_references": list(entry.named_references),
            "affected_targets": list(entry.affected_targets),
        }
        for entry in artifact.entries
    ]
    return "\n## Design Decisions\n```json\n" + json.dumps(payload, indent=2) + "\n```\n"


def _load_post_publish_review_result(run_dir: Path) -> PostPublishReviewResult | None:
    """Load post-publish review result from run directory."""
    path = run_dir / "post-publish-review-result.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    status = payload.get("status", "not_run")
    summary = payload.get("summary", "")
    pull_request_url = payload.get("pull_request_url")
    pull_number = payload.get("pull_number")
    reviewer_status = payload.get("reviewer_status", "not_run")
    reviewer_summary = payload.get("reviewer_summary", "")
    pull_head_sha = payload.get("pull_head_sha")
    reviewer_feedback = tuple(payload.get("reviewer_feedback", []))
    architect_status = payload.get("architect_status", "not_run")
    architect_summary = payload.get("architect_summary", "Architect review did not run.")
    architect_feedback = tuple(payload.get("architect_feedback", []))
    issue_comment_url = payload.get("issue_comment_url")
    issue_reopened = payload.get("issue_reopened", False)
    return PostPublishReviewResult(
        status=status,
        summary=summary,
        pull_request_url=pull_request_url,
        pull_number=pull_number,
        reviewer_status=reviewer_status,
        reviewer_summary=reviewer_summary,
        pull_head_sha=pull_head_sha,
        reviewer_feedback=reviewer_feedback,
        architect_status=architect_status,
        architect_summary=architect_summary,
        architect_feedback=architect_feedback,
        issue_comment_url=issue_comment_url,
        issue_reopened=issue_reopened,
    )


def _parse_issue_reference(issue_ref: str) -> IssueReference:
    """Parse an issue reference string like 'owner/repo#number'."""
    if "#" not in issue_ref:
        raise ValueError(f"Invalid issue reference format: {issue_ref}")
    repo_part, number_part = issue_ref.rsplit("#", 1)
    if "/" not in repo_part:
        raise ValueError(f"Invalid issue reference format: {issue_ref}")
    owner, repo = repo_part.rsplit("/", 1)
    try:
        number = int(number_part)
    except ValueError:
        raise ValueError(f"Invalid issue number: {number_part}")
    return IssueReference(owner=owner, repo=repo, number=number)


def apply_post_review_automation(
    run_id: str,
    approved: bool,
    *,
    token_env: str = "GITHUB_TOKEN",
) -> PostReviewAutomationResult:
    """Apply GitHub automation after post-publish review approval or rejection.

    On approval: marks PR ready, merges it, and closes the linked issue.
    On rejection: emits info log and returns early (rejection handled by post_publish_review.py).

    Args:
        run_id: The run ID to operate on.
        approved: Whether the review was approved.
        token_env: Environment variable name containing the GitHub token.

    Returns:
        PostReviewAutomationResult with status, summary, operations completed, and optional error.
    """
    if not approved:
        logger.info(
            "Post-review automation skipped: review was not approved. "
            "Rejection side-effects are handled by post_publish_review.py."
        )
        return PostReviewAutomationResult(
            status="skipped",
            summary="Automation skipped: review was not approved.",
            operations_completed=(),
            error=None,
        )

    store = RunStore(Path())
    try:
        run_record = store.load_run(run_id)
    except ValueError as exc:
        return PostReviewAutomationResult(
            status="failed",
            summary=f"Failed to load run record: {exc}",
            operations_completed=(),
            error=str(exc),
        )

    run_dir = Path(run_record.run_dir)
    review_result = _load_post_publish_review_result(run_dir)

    if review_result is None:
        return PostReviewAutomationResult(
            status="failed",
            summary="Post-publish review result not found.",
            operations_completed=(),
            error="post-publish-review-result.json not found in run directory.",
        )

    if review_result.pull_number is None or review_result.pull_request_url is None:
        return PostReviewAutomationResult(
            status="failed",
            summary="Post-publish review result is missing PR information.",
            operations_completed=(),
            error="pull_number or pull_request_url is None in review result.",
        )

    issue_ref = run_record.issue_ref
    try:
        issue_reference = _parse_issue_reference(issue_ref)
    except ValueError as exc:
        return PostReviewAutomationResult(
            status="failed",
            summary=f"Failed to parse issue reference: {exc}",
            operations_completed=(),
            error=str(exc),
        )

    owner = issue_reference.owner
    repo = issue_reference.repo
    pull_number = review_result.pull_number

    operations: list[str] = []

    def _execute_with_retry(operation_name: str, func) -> None:
        """Execute a GitHub operation with one retry on network timeout."""
        try:
            func()
            operations.append(operation_name)
        except GitHubClientError as exc:
            error_msg = str(exc)
            if "timed out" in error_msg.lower() or "urlopen" in error_msg.lower():
                logger.warning(f"{operation_name} timed out, retrying after 5 seconds...")
                time.sleep(5)
                try:
                    func()
                    operations.append(operation_name)
                    return
                except GitHubClientError as retry_exc:
                    raise retry_exc
            raise

    def _mark_ready():
        client.mark_pull_request_ready(owner, repo, pull_number)

    def _merge():
        client.merge_pull_request(owner, repo, pull_number)

    def _close_issue():
        client.close_issue(issue_reference)

    client = GitHubWriteClient.from_env(token_env=token_env)

    try:
        _execute_with_retry("mark_pull_request_ready", _mark_ready)
        _execute_with_retry("merge_pull_request", _merge)
        _execute_with_retry("close_issue", _close_issue)
    except GitHubClientError as exc:
        return PostReviewAutomationResult(
            status="failed",
            summary=f"Automation failed: {exc}",
            operations_completed=tuple(operations),
            error=str(exc),
        )

    return PostReviewAutomationResult(
        status="success",
        summary="Post-review automation completed successfully.",
        operations_completed=tuple(operations),
        error=None,
    )
