"""Post-publish PR review using local agent runtimes."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .github_client import GitHubWriteClient
from .models import IssueIntake, PostPublishReviewResult, ReviewAgentResult, RunRecord
from .opencode_model import resolve_opencode_model

PULL_NUMBER_PATTERN = re.compile(r"/pull/(?P<number>[0-9]+)$")


class ReviewRunner(Protocol):
    def review(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        pull_request_url: str,
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
    ) -> ReviewAgentResult:
        prefix = f"post-publish-{self.role}"
        stdout_path = run_dir / f"{prefix}.stdout.log"
        stderr_path = run_dir / f"{prefix}.stderr.log"
        transcript_path = run_dir / f"{prefix}-transcript.json"
        prompt = _build_review_prompt(
            role=self.role,
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            pull_request_url=pull_request_url,
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
        events = _extract_json_events(completed.stdout)
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
        return PostPublishReviewResult(
            status="not_run",
            summary="Post-publish review agents were not configured.",
            pull_request_url=pull_request_url,
            pull_number=pull_number,
            pull_head_sha=pull_head_sha,
            reviewer_status="not_run",
            reviewer_summary="Reviewer did not run.",
            architect_status="not_run",
            architect_summary="Architect did not run.",
        )

    reviewer_result = reviewer.review(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        pull_request_url=pull_request_url,
    )
    architect_result = architect.review(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        pull_request_url=pull_request_url,
    )
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
) -> str:
    return "\n".join(
        [
            f"Review role: {role}",
            f"Run ID: {run_record.run_id}",
            f"Issue: {intake.issue.reference}",
            f"PR: {pull_request_url}",
            "Review the published PR and respond with exactly one JSON object.",
            'Use the shape: {"status":"approved|rejected","summary":"...","feedback":["..."]}',
            "If you reject, feedback must contain concrete required changes.",
            "Do not include markdown fences.",
        ]
    )


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
        if status not in {"approved", "rejected"}:
            continue
        if not isinstance(summary, str):
            continue
        if not isinstance(feedback, list) or not all(isinstance(item, str) for item in feedback):
            continue
        return {
            "status": _as_review_status(status),
            "summary": summary,
            "feedback": tuple(feedback),
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


def _build_issue_feedback_comment(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    pull_request_url: str,
    reviewer_result: ReviewAgentResult,
    architect_result: ReviewAgentResult,
) -> str:
    reviewer_feedback = "\n".join(f"- {item}" for item in reviewer_result.feedback) or "- none"
    architect_feedback = "\n".join(f"- {item}" for item in architect_result.feedback) or "- none"
    return (
        "## Precision Squad Review Feedback\n"
        f"- Run ID: `{run_record.run_id}`\n"
        f"- Issue: `{intake.issue.reference}`\n"
        f"- PR: {pull_request_url}\n"
        f"- Reviewer verdict: `{reviewer_result.status}`\n"
        f"- Architect verdict: `{architect_result.status}`\n\n"
        "### Reviewer Findings\n"
        f"{reviewer_feedback}\n\n"
        "### Architect Findings\n"
        f"{architect_feedback}\n"
    )


def _extract_pull_number(pull_request_url: str) -> int | None:
    match = PULL_NUMBER_PATTERN.search(pull_request_url.strip())
    if match is None:
        return None
    return int(match.group("number"))
