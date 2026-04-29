"""Filesystem-backed run persistence."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import (
    EvaluationResult,
    ExecutionResult,
    GovernanceVerdict,
    IssueIntake,
    PostPublishReviewResult,
    PublishPlan,
    PublishResult,
    QaResult,
    RepairResult,
    RunRecord,
    RunRequest,
)

PersistedArtifact = (
    EvaluationResult
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

    def write_execution_result(self, run_dir: Path, result: ExecutionResult) -> None:
        self._write_json(run_dir / "execution-result.json", result)

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
