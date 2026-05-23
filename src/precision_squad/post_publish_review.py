"""Post-publish PR review using local agent runtimes."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from .github_client import GitHubWriteClient
from .json_events import extract_json_events
from .models import (
    AggregatedPlanAlignment,
    ImplReviewFeedback,
    ImplReviewResult,
    IssueIntake,
    PerAgentEvidence,
    PostPublishReviewResult,
    ReviewAgentResult,
    RunRecord,
)
from .opencode_model import resolve_opencode_model
from .stage_contracts import ReviewStageContract, load_review_stage_contract, render_review_prompt

PULL_NUMBER_PATTERN = re.compile(r"/pull/(?P<number>[0-9]+)$")
RUN_ID_MARKER_PATTERN = re.compile(r"^- Run ID: `(?P<run_id>[^`]+)`$", re.MULTILINE)
ISSUE_MARKER_PATTERN = re.compile(r"^- Issue: `(?P<issue_ref>[^`]+)`$", re.MULTILINE)
_PLAN_ALIGNMENT_VALUES = {
    "aligned",
    "justified_deviation",
    "unjustified_deviation",
    "non_material_detail",
}


class ReviewRunner(Protocol):
    def review(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        pull_request_url: str,
        review_contract: ReviewStageContract | None = None,
    ) -> ReviewAgentResult: ...


@dataclass(frozen=True, slots=True)
class OpenCodePrReviewAgent:
    """Runs an opencode agent against a published PR."""

    role: Literal["reviewer", "architect"]
    agent: str = "build"
    binary: str = "opencode"
    model: str | None = None

    def review(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        pull_request_url: str,
        review_contract: ReviewStageContract | None = None,
    ) -> ReviewAgentResult:
        prefix = f"post-publish-{self.role}"
        stdout_path = run_dir / f"{prefix}.stdout.log"
        stderr_path = run_dir / f"{prefix}.stderr.log"
        transcript_path = run_dir / f"{prefix}-transcript.json"
        try:
            prompt = _build_review_prompt(
                role=self.role,
                intake=intake,
                run_record=run_record,
                run_dir=run_dir,
                pull_request_url=pull_request_url,
                review_contract=review_contract,
            )
        except ValueError as exc:
            return ReviewAgentResult(
                role=self.role,
                status="failed_infra",
                summary=str(exc),
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                transcript_path=str(transcript_path),
            )
        command = [
            self.binary,
            "run",
            "--format",
            "json",
            "--agent",
            self.agent,
            "--dir",
            str(run_dir),
            "--dangerously-skip-permissions",
            prompt,
        ]
        resolved_model = resolve_opencode_model(self.model)
        if resolved_model:
            command[8:8] = ["--model", resolved_model]

        completed = subprocess.run(
            command,
            cwd=str(run_dir),
            capture_output=True,
            text=True,
        )
        stdout_path.write_text(completed.stdout, encoding="utf-8", errors="ignore")
        stderr_path.write_text(completed.stderr, encoding="utf-8", errors="ignore")
        events = extract_json_events(completed.stdout)
        transcript_path.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")
        parsed = _parse_review_output(events)

        if parsed is None:
            return ReviewAgentResult(
                role=self.role,
                status="failed_infra",
                summary=f"{self.role.title()} review agent could not produce a structured verdict.",
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                transcript_path=str(transcript_path),
            )

        return ReviewAgentResult(
            role=self.role,
            status=parsed["status"],
            summary=parsed["summary"],
            feedback=tuple(parsed["feedback"]),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            transcript_path=str(transcript_path),
            plan_alignment=parsed["plan_alignment"],
            plan_alignment_findings=tuple(parsed["plan_alignment_findings"]),
            justification_findings=tuple(parsed["justification_findings"]),
        )


def run_post_publish_review(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    pull_request_url: str,
    reviewer: ReviewRunner | None,
    architect: ReviewRunner | None,
    token_env: str = "GITHUB_TOKEN",
    apply_rejection_side_effects: bool = True,
) -> PostPublishReviewResult:
    pull_number = _extract_pull_number(pull_request_url)
    pull_head_sha = None
    if pull_number is not None:
        try:
            pull_head_sha = GitHubWriteClient.from_env(token_env).get_pull_request_head_sha(
                intake.issue.reference.owner,
                intake.issue.reference.repo,
                pull_number,
            )
        except Exception:
            pull_head_sha = None

    if reviewer is None or architect is None:
        reviewer_result = _result_stub(
            role="reviewer",
            status="not_run",
            summary="Reviewer did not run.",
        )
        architect_result = _result_stub(
            role="architect",
            status="not_run",
            summary="Architect did not run.",
        )
        return PostPublishReviewResult(
            status="not_run",
            summary="Post-publish review agents were not configured.",
            pull_request_url=pull_request_url,
            pull_number=pull_number,
            pull_head_sha=pull_head_sha,
            reviewer_status=reviewer_result.status,
            reviewer_summary=reviewer_result.summary,
            architect_status=architect_result.status,
            architect_summary=architect_result.summary,
            per_agent_evidence=_build_per_agent_evidence(reviewer_result, architect_result),
            aggregated_plan_alignment=_aggregate_plan_alignment(reviewer_result, architect_result),
        )

    try:
        review_contract = load_review_stage_contract(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            pull_request_url=pull_request_url,
            pull_number=pull_number,
            pull_head_sha=pull_head_sha,
            diff_loader=_fetch_pr_diff,
            pr_body_loader=_fetch_pr_body,
        )
    except ValueError as exc:
        reviewer_result = _result_stub(
            role="reviewer",
            status="failed_infra",
            summary=str(exc),
        )
        architect_result = _result_stub(
            role="architect",
            status="failed_infra",
            summary=str(exc),
        )
        return PostPublishReviewResult(
            status="failed_infra",
            summary=str(exc),
            pull_request_url=pull_request_url,
            pull_number=pull_number,
            pull_head_sha=pull_head_sha,
            reviewer_status=reviewer_result.status,
            reviewer_summary=reviewer_result.summary,
            architect_status=architect_result.status,
            architect_summary=architect_result.summary,
            per_agent_evidence=_build_per_agent_evidence(reviewer_result, architect_result),
            aggregated_plan_alignment=_aggregate_plan_alignment(reviewer_result, architect_result),
        )

    reviewer_result = reviewer.review(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        pull_request_url=pull_request_url,
        review_contract=review_contract,
    )
    architect_result = architect.review(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        pull_request_url=pull_request_url,
        review_contract=review_contract,
    )
    per_agent_evidence = _build_per_agent_evidence(reviewer_result, architect_result)
    aggregated_plan_alignment = _aggregate_plan_alignment(reviewer_result, architect_result)
    if reviewer_result.status == "approved" and architect_result.status == "approved":
        return PostPublishReviewResult(
            status="approved",
            summary="Reviewer and architect approved the published pull request.",
            pull_request_url=pull_request_url,
            pull_number=pull_number,
            pull_head_sha=pull_head_sha,
            reviewer_status=reviewer_result.status,
            reviewer_summary=reviewer_result.summary,
            reviewer_feedback=reviewer_result.feedback,
            architect_status=architect_result.status,
            architect_summary=architect_result.summary,
            architect_feedback=architect_result.feedback,
            per_agent_evidence=per_agent_evidence,
            aggregated_plan_alignment=aggregated_plan_alignment,
        )

    if "failed_infra" in {reviewer_result.status, architect_result.status}:
        return PostPublishReviewResult(
            status="failed_infra",
            summary="Post-publish review could not complete successfully.",
            pull_request_url=pull_request_url,
            pull_number=pull_number,
            pull_head_sha=pull_head_sha,
            reviewer_status=reviewer_result.status,
            reviewer_summary=reviewer_result.summary,
            reviewer_feedback=reviewer_result.feedback,
            architect_status=architect_result.status,
            architect_summary=architect_result.summary,
            architect_feedback=architect_result.feedback,
            per_agent_evidence=per_agent_evidence,
            aggregated_plan_alignment=aggregated_plan_alignment,
        )

    issue_comment_url = None
    issue_reopened = False
    if apply_rejection_side_effects:
        client = GitHubWriteClient.from_env(token_env)
        body = _build_issue_feedback_comment(
            intake=intake,
            run_record=run_record,
            pull_request_url=pull_request_url,
            reviewer_result=reviewer_result,
            architect_result=architect_result,
        )
        issue_comment_url = client.create_issue_comment(intake.issue.reference, body)
        client.reopen_issue(intake.issue.reference)
        issue_reopened = True
    return PostPublishReviewResult(
        status="rejected",
        summary="Post-publish review rejected the pull request and reopened the issue.",
        pull_request_url=pull_request_url,
        pull_number=pull_number,
        pull_head_sha=pull_head_sha,
        reviewer_status=reviewer_result.status,
        reviewer_summary=reviewer_result.summary,
        reviewer_feedback=reviewer_result.feedback,
        architect_status=architect_result.status,
        architect_summary=architect_result.summary,
        architect_feedback=architect_result.feedback,
        per_agent_evidence=per_agent_evidence,
        aggregated_plan_alignment=aggregated_plan_alignment,
        issue_comment_url=issue_comment_url,
        issue_reopened=issue_reopened,
    )


def run_impl_review(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    publish_plan_pull_request_url: str | None,
    publish_plan_pull_number: int | None,
    publish_result: object,
    reviewer: ReviewRunner | None,
    architect: ReviewRunner | None,
    token_env: str = "GITHUB_TOKEN",
) -> ImplReviewResult:
    published_status = getattr(publish_result, "status", None)
    published_target = getattr(publish_result, "target", None)
    if published_status != "published" or published_target != "draft_pr":
        return _finalize_non_approved_impl_review(
            intake=intake,
            run_record=run_record,
            summary="Implementation review requires a published draft PR for the same run.",
            feedback=(
                ImplReviewFeedback(
                    code="publish_not_reviewable",
                    message=(
                        "publish-result.json must indicate a published draft PR "
                        "before review impl can run."
                    ),
                    source="stage",
                ),
            ),
        )

    result_url = getattr(publish_result, "url", None)
    result_pull_number = getattr(publish_result, "pull_number", None)
    normalized_url, normalized_pull_number = _normalize_review_target(
        publish_plan_pull_request_url=publish_plan_pull_request_url,
        publish_plan_pull_number=publish_plan_pull_number,
        publish_result_url=result_url,
        publish_result_pull_number=result_pull_number,
    )
    if normalized_pull_number is None:
        return _finalize_non_approved_impl_review(
            intake=intake,
            run_record=run_record,
            summary="Implementation review could not normalize one coherent published PR target.",
            feedback=(
                ImplReviewFeedback(
                    code="pull_request_locator_invalid",
                    message=(
                        "publish-plan.json and publish-result.json must resolve "
                        "to one published PR URL and pull number."
                    ),
                    source="stage",
                ),
            ),
        )

    client = GitHubWriteClient.from_env(token_env)
    try:
        pr_payload = client.get_pull_request(
            intake.issue.reference.owner,
            intake.issue.reference.repo,
            normalized_pull_number,
        )
    except Exception as exc:
        return _finalize_non_approved_impl_review(
            intake=intake,
            run_record=run_record,
            summary="Implementation review could not fetch the published PR.",
            pull_request_url=normalized_url,
            pull_number=normalized_pull_number,
            feedback=(
                ImplReviewFeedback(
                    code="pull_request_fetch_failed",
                    message=f"Published PR lookup failed: {exc}",
                    source="stage",
                ),
            ),
        )

    live_url = pr_payload.get("html_url")
    if not isinstance(live_url, str) or not live_url.strip():
        return _finalize_non_approved_impl_review(
            intake=intake,
            run_record=run_record,
            summary="Implementation review requires a live published PR URL.",
            pull_request_url=normalized_url,
            pull_number=normalized_pull_number,
            feedback=(
                ImplReviewFeedback(
                    code="pull_request_url_missing",
                    message="Live PR payload did not include html_url.",
                    source="stage",
                ),
            ),
        )

    live_head_sha = _extract_live_pull_head_sha(pr_payload)
    if not live_head_sha:
        return _finalize_non_approved_impl_review(
            intake=intake,
            run_record=run_record,
            summary="Implementation review requires the live PR head SHA.",
            pull_request_url=live_url,
            pull_number=normalized_pull_number,
            feedback=(
                ImplReviewFeedback(
                    code="pull_head_sha_missing",
                    message="Live PR payload did not expose head.sha for review provenance.",
                    source="stage",
                ),
            ),
        )

    pr_body = _fetch_pr_body(intake.issue.reference.owner, intake.issue.reference.repo, live_url)
    if not isinstance(pr_body, str) or not pr_body.strip():
        return _finalize_non_approved_impl_review(
            intake=intake,
            run_record=run_record,
            summary="Implementation review requires the live PR body.",
            pull_request_url=live_url,
            pull_number=normalized_pull_number,
            pull_head_sha=live_head_sha,
            feedback=(
                ImplReviewFeedback(
                    code="pull_request_body_missing",
                    message="Published PR body is missing or empty.",
                    source="stage",
                ),
            ),
        )

    pr_diff = _fetch_pr_diff(intake.issue.reference.owner, intake.issue.reference.repo, live_url)
    if not pr_diff.strip():
        return _finalize_non_approved_impl_review(
            intake=intake,
            run_record=run_record,
            summary="Implementation review requires the live PR diff.",
            pull_request_url=live_url,
            pull_number=normalized_pull_number,
            pull_head_sha=live_head_sha,
            feedback=(
                ImplReviewFeedback(
                    code="pull_request_diff_missing",
                    message="Published PR diff is missing or empty.",
                    source="stage",
                ),
            ),
        )

    provenance_feedback = _validate_review_provenance(
        intake=intake,
        run_record=run_record,
        pr_payload=pr_payload,
        pr_body=pr_body,
        normalized_pull_number=normalized_pull_number,
        normalized_url=normalized_url,
        live_url=live_url,
    )
    if provenance_feedback:
        return _finalize_non_approved_impl_review(
            intake=intake,
            run_record=run_record,
            summary=(
                "Implementation review could not validate published PR provenance "
                "for this run."
            ),
            pull_request_url=live_url,
            pull_number=normalized_pull_number,
            pull_head_sha=live_head_sha,
            feedback=tuple(provenance_feedback),
        )

    legacy_result = run_post_publish_review(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        pull_request_url=live_url,
        reviewer=reviewer,
        architect=architect,
        token_env=token_env,
        apply_rejection_side_effects=False,
    )
    mapped_review = _map_post_publish_to_impl_review(legacy_result)
    if mapped_review.pull_head_sha != live_head_sha:
        mapped_review = ImplReviewResult(
            review_status=mapped_review.review_status,
            summary=mapped_review.summary,
            pull_request_url=mapped_review.pull_request_url,
            pull_number=mapped_review.pull_number,
            pull_head_sha=live_head_sha,
            feedback=mapped_review.feedback,
            reviewer_status=mapped_review.reviewer_status,
            reviewer_summary=mapped_review.reviewer_summary,
            architect_status=mapped_review.architect_status,
            architect_summary=mapped_review.architect_summary,
            issue_comment_url=mapped_review.issue_comment_url,
            issue_reopened=mapped_review.issue_reopened,
        )
    return _finalize_non_approved_impl_review(
        intake=intake,
        run_record=run_record,
        review=mapped_review,
        token_env=token_env,
    )


def mirror_impl_review_to_post_publish(review: ImplReviewResult) -> PostPublishReviewResult:
    status = cast(
        Literal["approved", "rejected", "failed_infra", "not_run"],
        {
        "approved": "approved",
        "changes_requested": "rejected",
        "blocked": "failed_infra",
        }[review.review_status],
    )
    return PostPublishReviewResult(
        status=status,
        summary=review.summary,
        pull_request_url=review.pull_request_url,
        pull_number=review.pull_number,
        pull_head_sha=review.pull_head_sha,
        reviewer_status=review.reviewer_status,
        reviewer_summary=review.reviewer_summary,
        architect_status=review.architect_status,
        architect_summary=review.architect_summary,
        issue_comment_url=review.issue_comment_url,
        issue_reopened=review.issue_reopened,
    )


def _build_review_prompt(
    *,
    role: str,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    pull_request_url: str,
    review_contract: ReviewStageContract | None = None,
) -> str:
    if review_contract is None:
        review_contract = load_review_stage_contract(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            pull_request_url=pull_request_url,
            pull_number=_extract_pull_number(pull_request_url),
            pull_head_sha=None,
            diff_loader=_fetch_pr_diff,
            pr_body_loader=_fetch_pr_body,
        )
    return render_review_prompt(role, review_contract)


def _fetch_pr_diff(owner: str, repo: str, pull_request_url: str) -> str:
    match = PULL_NUMBER_PATTERN.search(pull_request_url.strip())
    if match is None:
        return ""
    pull_number = int(match.group("number"))
    payload = GitHubWriteClient.from_env().get_pull_request(owner, repo, pull_number)
    diff_url = payload.get("diff_url")
    if not isinstance(diff_url, str) or not diff_url:
        return ""
    completed = subprocess.run(
        ["gh", "api", diff_url, "-H", "Accept: application/vnd.github.v3.diff"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _fetch_pr_body(owner: str, repo: str, pull_request_url: str) -> str | None:
    match = PULL_NUMBER_PATTERN.search(pull_request_url.strip())
    if match is None:
        return None
    pull_number = int(match.group("number"))
    payload = GitHubWriteClient.from_env().get_pull_request(owner, repo, pull_number)
    body = payload.get("body")
    return body if isinstance(body, str) else None


def _parse_review_output(events: list[dict]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("type") != "text":
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if not isinstance(text, str):
            continue
        payload = _extract_review_payload(text)
        if payload is None:
            continue
        status = payload.get("status")
        summary = payload.get("summary")
        feedback = payload.get("feedback")
        plan_alignment = payload.get("plan_alignment")
        plan_alignment_findings = payload.get("plan_alignment_findings")
        justification_findings = payload.get("justification_findings")
        if status not in {"approved", "rejected"}:
            continue
        if not isinstance(summary, str):
            continue
        if not isinstance(feedback, list) or not all(isinstance(item, str) for item in feedback):
            continue
        if plan_alignment not in _PLAN_ALIGNMENT_VALUES:
            continue
        if not isinstance(plan_alignment_findings, list) or not all(
            isinstance(item, str) for item in plan_alignment_findings
        ):
            continue
        if not isinstance(justification_findings, list) or not all(
            isinstance(item, str) for item in justification_findings
        ):
            continue
        return {
            "status": _as_review_status(status),
            "summary": summary,
            "feedback": tuple(feedback),
            "plan_alignment": _as_plan_alignment(plan_alignment),
            "plan_alignment_findings": tuple(plan_alignment_findings),
            "justification_findings": tuple(justification_findings),
        }
    return None


def _extract_review_payload(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("{"):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    start = candidate.rfind("{")
    if start == -1:
        return None
    json_candidate = candidate[start:]
    try:
        payload = json.loads(json_candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _as_review_status(value: object) -> Literal["approved", "rejected"]:
    if value == "approved":
        return "approved"
    if value == "rejected":
        return "rejected"
    raise ValueError("Expected review status")


def _as_plan_alignment(
    value: object,
) -> Literal["aligned", "justified_deviation", "unjustified_deviation", "non_material_detail"]:
    if value == "aligned":
        return "aligned"
    if value == "justified_deviation":
        return "justified_deviation"
    if value == "unjustified_deviation":
        return "unjustified_deviation"
    if value == "non_material_detail":
        return "non_material_detail"
    raise ValueError("Expected plan alignment")


def _blocked_impl_review(
    *,
    summary: str,
    feedback: tuple[ImplReviewFeedback, ...],
    pull_request_url: str | None = None,
    pull_number: int | None = None,
    pull_head_sha: str | None = None,
) -> ImplReviewResult:
    return ImplReviewResult(
        review_status="blocked",
        summary=summary,
        pull_request_url=pull_request_url,
        pull_number=pull_number,
        pull_head_sha=pull_head_sha,
        feedback=feedback,
        reviewer_status="not_run",
        reviewer_summary="Reviewer did not run because review impl was blocked.",
        architect_status="not_run",
        architect_summary="Architect did not run because review impl was blocked.",
    )


def _normalize_review_target(
    *,
    publish_plan_pull_request_url: str | None,
    publish_plan_pull_number: int | None,
    publish_result_url: str | None,
    publish_result_pull_number: int | None,
) -> tuple[str | None, int | None]:
    candidate_url = publish_result_url or publish_plan_pull_request_url
    candidate_number = publish_result_pull_number or publish_plan_pull_number
    url_number = _extract_pull_number(candidate_url) if candidate_url else None

    if publish_plan_pull_number is not None and publish_result_pull_number is not None:
        if publish_plan_pull_number != publish_result_pull_number:
            return None, None
    if (
        publish_plan_pull_request_url
        and publish_result_url
        and publish_plan_pull_request_url != publish_result_url
    ):
        return None, None
    if candidate_number is None and url_number is not None:
        candidate_number = url_number
    if candidate_number is None:
        return None, None
    if candidate_url is not None and url_number is not None and url_number != candidate_number:
        return None, None
    return candidate_url, candidate_number


def _extract_live_pull_head_sha(pr_payload: dict[str, Any]) -> str | None:
    head = pr_payload.get("head")
    if not isinstance(head, dict):
        return None
    sha = head.get("sha")
    return sha if isinstance(sha, str) and sha.strip() else None


def _validate_review_provenance(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    pr_payload: dict[str, Any],
    pr_body: str,
    normalized_pull_number: int,
    normalized_url: str | None,
    live_url: str,
) -> list[ImplReviewFeedback]:
    feedback: list[ImplReviewFeedback] = []

    live_number = pr_payload.get("number")
    if live_number != normalized_pull_number:
        feedback.append(
            ImplReviewFeedback(
                code="pull_request_number_mismatch",
                message="Live PR number does not match persisted publish artifacts.",
                source="stage",
            )
        )

    if normalized_url is not None and live_url != normalized_url:
        feedback.append(
            ImplReviewFeedback(
                code="pull_request_url_mismatch",
                message="Live PR URL does not match persisted publish artifacts.",
                source="stage",
            )
        )

    base = pr_payload.get("base")
    repo_payload = base.get("repo") if isinstance(base, dict) else None
    owner_payload = repo_payload.get("owner") if isinstance(repo_payload, dict) else None
    repo_name = repo_payload.get("name") if isinstance(repo_payload, dict) else None
    owner_login = owner_payload.get("login") if isinstance(owner_payload, dict) else None
    if owner_login != intake.issue.reference.owner or repo_name != intake.issue.reference.repo:
        feedback.append(
            ImplReviewFeedback(
                code="repository_identity_mismatch",
                message="Live PR repository identity does not match issue-intake.json.",
                source="stage",
            )
        )

    run_id_match = RUN_ID_MARKER_PATTERN.search(pr_body)
    issue_match = ISSUE_MARKER_PATTERN.search(pr_body)
    if run_id_match is None:
        feedback.append(
            ImplReviewFeedback(
                code="pr_body_run_id_missing",
                message="Published PR body is missing the Run ID provenance marker.",
                source="stage",
            )
        )
    elif run_id_match.group("run_id") != run_record.run_id:
        feedback.append(
            ImplReviewFeedback(
                code="pr_body_run_id_mismatch",
                message="Published PR Run ID marker does not match run-record.json.",
                source="stage",
            )
        )

    if issue_match is None:
        feedback.append(
            ImplReviewFeedback(
                code="pr_body_issue_missing",
                message="Published PR body is missing the Issue provenance marker.",
                source="stage",
            )
        )
    elif issue_match.group("issue_ref") != str(intake.issue.reference):
        feedback.append(
            ImplReviewFeedback(
                code="pr_body_issue_mismatch",
                message=(
                    "Published PR Issue marker does not match the canonical issue "
                    "being reviewed."
                ),
                source="stage",
            )
        )

    return feedback


def _map_post_publish_to_impl_review(result: PostPublishReviewResult) -> ImplReviewResult:
    if result.status == "approved":
        return ImplReviewResult(
            review_status="approved",
            summary=result.summary,
            pull_request_url=result.pull_request_url,
            pull_number=result.pull_number,
            pull_head_sha=result.pull_head_sha,
            feedback=(),
            reviewer_status=result.reviewer_status,
            reviewer_summary=result.reviewer_summary,
            architect_status=result.architect_status,
            architect_summary=result.architect_summary,
            issue_comment_url=result.issue_comment_url,
            issue_reopened=result.issue_reopened,
        )
    if result.status == "rejected":
        feedback: list[ImplReviewFeedback] = []
        for message in result.reviewer_feedback:
            feedback.append(
                ImplReviewFeedback(
                    code="reviewer_changes_requested",
                    message=message,
                    source="reviewer",
                )
            )
        for message in result.architect_feedback:
            feedback.append(
                ImplReviewFeedback(
                    code="architect_changes_requested",
                    message=message,
                    source="architect",
                )
            )
        if not feedback:
            feedback.append(
                ImplReviewFeedback(
                    code="changes_requested",
                    message=(
                        "Published PR requires changes before downstream automation "
                        "may proceed."
                    ),
                    source="stage",
                )
            )
        return ImplReviewResult(
            review_status="changes_requested",
            summary=result.summary,
            pull_request_url=result.pull_request_url,
            pull_number=result.pull_number,
            pull_head_sha=result.pull_head_sha,
            feedback=tuple(feedback),
            reviewer_status=result.reviewer_status,
            reviewer_summary=result.reviewer_summary,
            architect_status=result.architect_status,
            architect_summary=result.architect_summary,
            issue_comment_url=result.issue_comment_url,
            issue_reopened=result.issue_reopened,
        )
    return ImplReviewResult(
        review_status="blocked",
        summary=result.summary,
        pull_request_url=result.pull_request_url,
        pull_number=result.pull_number,
        pull_head_sha=result.pull_head_sha,
        feedback=(
            ImplReviewFeedback(
                code="review_infrastructure_blocked",
                message=result.summary,
                source="stage",
            ),
        ),
        reviewer_status=result.reviewer_status,
        reviewer_summary=result.reviewer_summary,
        architect_status=result.architect_status,
        architect_summary=result.architect_summary,
        issue_comment_url=result.issue_comment_url,
        issue_reopened=result.issue_reopened,
    )


def _finalize_non_approved_impl_review(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    token_env: str = "GITHUB_TOKEN",
    review: ImplReviewResult | None = None,
    summary: str | None = None,
    feedback: tuple[ImplReviewFeedback, ...] = (),
    pull_request_url: str | None = None,
    pull_number: int | None = None,
    pull_head_sha: str | None = None,
) -> ImplReviewResult:
    result = review or _blocked_impl_review(
        summary=summary or "Implementation review is blocked.",
        feedback=feedback,
        pull_request_url=pull_request_url,
        pull_number=pull_number,
        pull_head_sha=pull_head_sha,
    )
    if result.review_status == "approved":
        return result

    client = GitHubWriteClient.from_env(token_env)
    body = _build_impl_review_issue_comment(
        intake=intake,
        run_record=run_record,
        review=result,
    )
    issue_comment_url = client.create_issue_comment(intake.issue.reference, body)
    client.reopen_issue(intake.issue.reference)
    return ImplReviewResult(
        review_status=result.review_status,
        summary=result.summary,
        pull_request_url=result.pull_request_url,
        pull_number=result.pull_number,
        pull_head_sha=result.pull_head_sha,
        feedback=result.feedback,
        reviewer_status=result.reviewer_status,
        reviewer_summary=result.reviewer_summary,
        architect_status=result.architect_status,
        architect_summary=result.architect_summary,
        issue_comment_url=issue_comment_url,
        issue_reopened=True,
    )


def _build_impl_review_issue_comment(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    review: ImplReviewResult,
) -> str:
    lines = [
        "## Precision Squad Implementation Review",
        f"- Run ID: `{run_record.run_id}`",
        f"- Issue: `{intake.issue.reference}`",
        f"- Review status: `{review.review_status}`",
        f"- PR: {review.pull_request_url or '(unavailable)'}",
        f"- PR Head SHA: `{review.pull_head_sha or '(unavailable)'}`",
        "",
        "### Structured Feedback",
    ]
    for item in review.feedback:
        lines.append(f"- `{item.code}` [{item.source}] {item.message}")
    return "\n".join(lines) + "\n"


def _build_issue_feedback_comment(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    pull_request_url: str,
    reviewer_result: ReviewAgentResult,
    architect_result: ReviewAgentResult,
) -> str:
    rejection_sections = _build_rejection_sections(reviewer_result, architect_result)
    return (
        "## Precision Squad Review Feedback\n"
        f"- Run ID: `{run_record.run_id}`\n"
        f"- Issue: `{intake.issue.reference}`\n"
        f"- PR: {pull_request_url}\n"
        f"- Reviewer verdict: `{reviewer_result.status}`\n"
        f"- Architect verdict: `{architect_result.status}`\n\n"
        f"{rejection_sections}\n"
    )


def _extract_pull_number(pull_request_url: str) -> int | None:
    match = PULL_NUMBER_PATTERN.search(pull_request_url.strip())
    if match is None:
        return None
    return int(match.group("number"))


def _result_stub(
    *,
    role: Literal["reviewer", "architect"],
    status: Literal["failed_infra", "not_run"],
    summary: str,
) -> ReviewAgentResult:
    return ReviewAgentResult(role=role, status=status, summary=summary)


def _build_per_agent_evidence(
    reviewer_result: ReviewAgentResult,
    architect_result: ReviewAgentResult,
) -> PerAgentEvidence:
    return PerAgentEvidence(reviewer=reviewer_result, architect=architect_result)


def _aggregate_plan_alignment(
    reviewer_result: ReviewAgentResult,
    architect_result: ReviewAgentResult,
) -> AggregatedPlanAlignment:
    ordered_results = (reviewer_result, architect_result)
    statuses = {result.status for result in ordered_results}
    if "failed_infra" in statuses or "not_run" in statuses:
        classification = None
    else:
        classifications = {result.plan_alignment for result in ordered_results}
        if "unjustified_deviation" in classifications:
            classification = "unjustified_deviation"
        elif "justified_deviation" in classifications:
            classification = "justified_deviation"
        elif "non_material_detail" in classifications:
            classification = "non_material_detail"
        else:
            classification = "aligned"

    return AggregatedPlanAlignment(
        classification=classification,
        plan_alignment_findings=_dedupe_preserving_order(
            item for result in ordered_results for item in result.plan_alignment_findings
        ),
        justification_findings=_dedupe_preserving_order(
            item for result in ordered_results for item in result.justification_findings
        ),
    )


def _dedupe_preserving_order(items: Any) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


def _build_rejection_sections(
    reviewer_result: ReviewAgentResult,
    architect_result: ReviewAgentResult,
) -> str:
    sections: list[str] = []
    for result in (reviewer_result, architect_result):
        if result.status != "rejected":
            continue
        sections.append(f"### {result.role.title()} Rejection")
        sections.append(f"- Plan alignment: `{result.plan_alignment}`")
        sections.extend(f"- {bullet}" for bullet in _comment_bullets_for_rejection(result))
        sections.append("")
    return "\n".join(sections).strip()


def _comment_bullets_for_rejection(result: ReviewAgentResult) -> tuple[str, ...]:
    concrete: list[str] = []
    concrete.extend(item for item in result.plan_alignment_findings if item.strip())
    concrete.extend(item for item in result.justification_findings if item.strip())
    if not concrete:
        concrete.extend(item for item in result.feedback if item.strip())
    if not concrete:
        concrete.append("Concrete rejection details were not provided by the review agent.")
    return tuple(dict.fromkeys(concrete[:3]))
