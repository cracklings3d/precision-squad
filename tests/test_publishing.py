"""Tests for publish plan preparation."""

from __future__ import annotations

import json
from pathlib import Path

from precision_squad.models import (
    GitHubIssue,
    GovernanceVerdict,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RepairResult,
    RunRecord,
    SideIssue,
)
from precision_squad.publishing import build_publish_plan


def test_build_publish_plan_creates_draft_pr_for_approved() -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    verdict = GovernanceVerdict(
        status="approved",
        summary="QA passed.",
        reason_codes=(),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert plan.status == "draft_pr"
    assert plan.title == "Add --version flag to CLI"


def test_build_publish_plan_embeds_blocker_fingerprint_for_follow_up_issue() -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    run_dir = Path(run_record.run_dir)
    (run_dir / "execution-contract").mkdir(parents=True, exist_ok=True)
    (run_dir / "execution-contract" / "contract.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "rule_id": "docs_qa_command_missing",
                        "source_path": "readme.md",
                        "section_key": "testing",
                        "subject_key": "qa-command",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    verdict = GovernanceVerdict(
        status="blocked",
        summary="Missing documented QA command.",
        reason_codes=("docs_qa_command_missing",),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert plan.status == "follow_up_issue"
    assert "precision-squad:blocker-fingerprint:" in plan.body
    assert "precision-squad:blocker-findings:" in plan.body
    assert "precision-squad:target-findings:" in plan.body
    assert "precision-squad:baseline-findings:" in plan.body
    assert "docs_qa_command_missing" in plan.body


def test_build_publish_plan_uses_specific_contract_findings_for_umbrella_docs_reason() -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 17),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/17",
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#17",
        status="runnable",
        created_at="2026-04-29T00:00:00Z",
        updated_at="2026-04-29T00:00:00Z",
        run_dir=".precision-squad/runs/run-123-specific",
    )
    run_dir = Path(run_record.run_dir)
    (run_dir / "execution-contract").mkdir(parents=True, exist_ok=True)
    (run_dir / "execution-contract" / "contract.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "rule_id": "docs_setup_prerequisite_manual_only",
                        "source_path": "readme.md",
                        "section_key": "windows-system-dependencies",
                        "subject_key": "gtk3-runtime",
                    },
                    {
                        "rule_id": "docs_environment_assumptions_explicit",
                        "source_path": "readme.md",
                        "section_key": "windows-system-dependencies",
                        "subject_key": "gtk3-runtime",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    verdict = GovernanceVerdict(
        status="blocked",
        summary="Prerequisites are ambiguous.",
        reason_codes=("docs_setup_prerequisites_ambiguous",),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert plan.status == "follow_up_issue"
    assert "docs_setup_prerequisite_manual_only" in plan.body
    assert "docs_environment_assumptions_explicit" in plan.body
    assert "docs_setup_prerequisites_ambiguous\"" not in plan.body


def test_build_publish_plan_does_not_recurse_follow_up_issue_for_docs_remediation_issue() -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body="<!-- precision-squad:docs-remediation -->\n\n## Context\nFix docs.",
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#16",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    verdict = GovernanceVerdict(
        status="blocked",
        summary="Missing documented QA command.",
        reason_codes=("docs_qa_command_missing",),
    )

    plan = build_publish_plan(intake, run_record, verdict)

    assert plan.status == "issue_comment"


def test_build_publish_plan_creates_follow_up_issue_for_side_issues() -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    verdict = GovernanceVerdict(
        status="blocked",
        summary="QA failed.",
        reason_codes=("qa_failed",),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair completed with side issues.",
        detail_codes=("repair_stage_completed",),
        side_issues=(
            SideIssue(
                title="Missing version pin",
                summary="requirements.txt lacks version pin for pytest",
                body="Full details here",
                labels=("docs", "bug"),
            ),
            SideIssue(
                title="CI badge broken",
                summary="Travis CI badge returns 404",
                body="The badge URL has changed",
                labels=("ci",),
            ),
        ),
    )

    plan = build_publish_plan(intake, run_record, verdict, repair_result)

    assert plan.status == "follow_up_issue"
    assert "Side issues surfaced" in plan.title
    assert "Missing version pin" in plan.body
    assert "CI badge broken" in plan.body
    assert "`docs`, `bug`" in plan.body
    assert "`ci`" in plan.body
    assert "requirements.txt lacks version pin" in plan.body


def test_build_publish_plan_returns_issue_comment_when_no_side_issues() -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
    run_record = RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-28T00:00:00Z",
        updated_at="2026-04-28T00:00:00Z",
        run_dir=".precision-squad/runs/run-123",
    )
    verdict = GovernanceVerdict(
        status="blocked",
        summary="QA failed.",
        reason_codes=("qa_failed",),
    )
    repair_result = RepairResult(
        status="completed",
        summary="Repair completed.",
        detail_codes=("repair_stage_completed",),
        side_issues=(),
    )

    plan = build_publish_plan(intake, run_record, verdict, repair_result)

    assert plan.status == "issue_comment"
