"""Prepare GitHub-facing publish plans."""

from __future__ import annotations

from pathlib import Path

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
from .intake import is_docs_remediation_issue
from .models import GovernanceVerdict, IssueIntake, PublishPlan, RunRecord
from .rerun_context import latest_rejected_pull_request


def build_publish_plan(
    intake: IssueIntake,
    run_record: RunRecord,
    verdict: GovernanceVerdict,
) -> PublishPlan:
    """Prepare the first publish plan without calling GitHub yet."""
    if verdict.status in {"approved", "provisional"}:
        context_heading = (
            "## Summary\n"
            if verdict.status == "approved"
            else "## Provisional Summary\n"
        )
        context_note = "" if verdict.status == "approved" else (
            "- Quality state: `provisional` (baseline-tolerant, not fully green)\n"
        )
        rejected_pr = latest_rejected_pull_request(intake.issue.comments)
        return PublishPlan(
            status="draft_pr",
            title=intake.summary,
            body=(
                context_heading
                + f"- Run ID: `{run_record.run_id}`\n"
                + f"- Issue: `{intake.issue.reference}`\n"
                + f"- Governance verdict: `{verdict.status}`\n"
                + context_note
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

    reason_lines = "\n".join(f"- {code}" for code in verdict.reason_codes) or "- blocked"
    return PublishPlan(
        status="issue_comment",
        title=f"Blocked: {intake.summary}",
        body=(
            "## Blocked\n"
            f"- Run ID: `{run_record.run_id}`\n"
            f"- Issue: `{intake.issue.reference}`\n"
            f"- Verdict: `{verdict.status}`\n"
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
        verdict.status == "blocked"
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
