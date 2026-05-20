"""Post-publish PR review using local agent runtimes."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .github_client import GitHubWriteClient
from .json_events import extract_json_events
from .models import (
    AggregatedPlanAlignment,
    IssueIntake,
    PerAgentEvidence,
    PostPublishReviewResult,
    ReviewAgentResult,
    RunRecord,
)
from .opencode_model import resolve_opencode_model
from .stage_contracts import ReviewStageContract, load_review_stage_contract, render_review_prompt

PULL_NUMBER_PATTERN = re.compile(r"/pull/(?P<number>[0-9]+)$")
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
        issue_reopened=True,
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
