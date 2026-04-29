"""Issue intake parsing, normalization, and classification."""

from __future__ import annotations

import re

from .docs_remediation import is_docs_remediation_title_or_body
from .github_client import GitHubIssueClient
from .models import GitHubIssue, IssueAssessment, IssueIntake, IssueReference

ISSUE_REFERENCE_PATTERN = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)#(?P<number>[1-9][0-9]*)$"
)
TITLE_TAG_PATTERN = re.compile(r"^\[[^\]]+\]\s*")
CHECKLIST_PATTERN = re.compile(r"^- \[[ xX]\]", re.MULTILINE)
HEADING_PATTERN = re.compile(r"^#{2,6}\s+", re.MULTILINE)


def parse_issue_reference(raw: str) -> IssueReference:
    """Parse an issue reference in owner/repo#number form."""
    match = ISSUE_REFERENCE_PATTERN.fullmatch(raw.strip())
    if match is None:
        raise ValueError(
            "Issue references must use the form owner/repo#number, for example "
            "cracklings3d/markdown-pdf-renderer#9."
        )

    return IssueReference(
        owner=match.group("owner"),
        repo=match.group("repo"),
        number=int(match.group("number")),
    )


def assess_issue(issue: GitHubIssue) -> IssueAssessment:
    """Determine whether the issue is runnable or should be blocked."""
    if is_docs_remediation_issue(issue):
        return IssueAssessment(status="runnable", reason_codes=())

    title = issue.title.strip().lower()
    body = issue.body.strip().lower()
    reason_codes: list[str] = []

    if title.startswith("[plan]"):
        reason_codes.append("issue_marked_as_plan")

    planning_markers = [
        "project plan",
        "tech stack",
        "overview",
        "first pr scope",
        "optional enhancements",
        "dependencies",
        "file structure",
        "roadmap",
    ]
    matched_markers = sum(marker in body for marker in planning_markers)
    heading_count = len(HEADING_PATTERN.findall(issue.body))
    checklist_count = len(CHECKLIST_PATTERN.findall(issue.body))

    if matched_markers >= 3:
        reason_codes.append("issue_body_reads_like_project_plan")

    if heading_count >= 4 and checklist_count >= 4:
        reason_codes.append("issue_spans_multiple_features")

    if len(issue.body) > 1500 and heading_count >= 4:
        reason_codes.append("issue_too_broad_for_single_run")

    status = "blocked" if reason_codes else "runnable"
    return IssueAssessment(status=status, reason_codes=tuple(reason_codes))


def build_issue_intake(issue: GitHubIssue) -> IssueIntake:
    """Normalize a fetched issue into the intake artifact."""
    summary = TITLE_TAG_PATTERN.sub("", issue.title).strip() or issue.title.strip()
    problem_statement = _extract_problem_statement(issue.body) or summary
    assessment = assess_issue(issue)
    return IssueIntake(
        issue=issue,
        summary=summary,
        problem_statement=problem_statement,
        assessment=assessment,
    )


def load_issue_intake(issue_ref: str, token_env: str = "GITHUB_TOKEN") -> IssueIntake:
    """Fetch and normalize GitHub issue intake."""
    reference = parse_issue_reference(issue_ref)
    client = GitHubIssueClient.from_env(token_env)
    issue = client.fetch_issue(reference)
    return build_issue_intake(issue)


def is_docs_remediation_issue(issue: GitHubIssue | IssueIntake) -> bool:
    """Return whether the issue exists to remediate repo documentation blockers."""
    issue_payload = issue.issue if isinstance(issue, IssueIntake) else issue
    return is_docs_remediation_title_or_body(issue_payload.title, issue_payload.body)


def _extract_problem_statement(body: str) -> str:
    blocks = [block.strip() for block in body.split("\n\n") if block.strip()]
    for block in blocks:
        first_line = block.splitlines()[0].strip()
        if first_line.startswith("#"):
            remainder = "\n".join(line for line in block.splitlines()[1:] if line.strip()).strip()
            if remainder:
                return remainder
            continue
        if CHECKLIST_PATTERN.match(first_line):
            continue
        if first_line.startswith("```"):
            continue
        return block
    return ""
