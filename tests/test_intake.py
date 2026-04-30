"""Tests for issue intake parsing and classification."""

from __future__ import annotations

import pytest

from precision_squad.intake import (
    build_issue_intake,
    is_docs_remediation_issue,
    parse_issue_reference,
)
from precision_squad.models import GitHubIssue, IssueReference

PLAN_ISSUE = GitHubIssue(
    reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 1),
    title="[Plan] Markdown to PDF Renderer",
    body="""## Project Plan: Markdown to PDF Renderer

### Overview
A CLI tool and library that converts Markdown files to styled PDF documents.

### Tech Stack
- **Language**: Node.js with TypeScript
- **Rendering**: Puppeteer (Chromium) for accurate HTML/CSS rendering

### Features
- [ ] CLI interface
- [ ] API for programmatic use
- [ ] Support for GFM
- [ ] Code syntax highlighting

### Optional Enhancements
- [ ] Watching mode for development
- [ ] Table of contents generation

### First PR Scope
1. Project setup
2. Basic markdown → HTML conversion
3. HTML → PDF via Puppeteer
""",
    labels=("plan",),
    html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/1",
)

BOUNDED_ISSUE = GitHubIssue(
    reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
    title="[Enhancement] Add --version flag to CLI",
    body="""## Description
Add a `--version` flag to the CLI:

```bash
md-pdf --version
```

Currently `md-pdf --version` is not supported.
""",
    labels=("enhancement",),
    html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
)


def test_parse_issue_reference_accepts_expected_format() -> None:
    reference = parse_issue_reference("cracklings3d/markdown-pdf-renderer#9")

    assert reference.owner == "cracklings3d"
    assert reference.repo == "markdown-pdf-renderer"
    assert reference.number == 9


def test_parse_issue_reference_rejects_invalid_format() -> None:
    with pytest.raises(ValueError):
        parse_issue_reference("markdown-pdf-renderer#9")


def test_build_issue_intake_blocks_plan_issue() -> None:
    intake = build_issue_intake(PLAN_ISSUE)

    assert intake.assessment.status == "blocked"
    assert "issue_marked_as_plan" in intake.assessment.reason_codes


def test_build_issue_intake_accepts_bounded_issue() -> None:
    intake = build_issue_intake(BOUNDED_ISSUE)

    assert intake.assessment.status == "runnable"
    assert intake.summary == "Add --version flag to CLI"
    assert "Add a `--version` flag to the CLI" in intake.problem_statement


def test_build_issue_intake_preserves_issue_comments() -> None:
    issue = GitHubIssue(
        reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
        title="[Enhancement] Add --version flag to CLI",
        body="## Description\nAdd a version flag.",
        labels=("enhancement",),
        html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
        comments=("Needs follow-up from review.",),
    )

    intake = build_issue_intake(issue)

    assert intake.issue.comments == ("Needs follow-up from review.",)


def test_is_docs_remediation_issue_detects_marker_and_legacy_title() -> None:
    assert is_docs_remediation_issue(
        GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body="## Context\n...",
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        )
    )
    assert is_docs_remediation_issue(
        GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 17),
            title="Clarify setup docs",
            body="<!-- precision-squad:docs-remediation -->\n\n## Context",
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/17",
        )
    )


def test_build_issue_intake_keeps_docs_remediation_issue_runnable_despite_long_body() -> None:
    issue = GitHubIssue(
        reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 18),
        title="Docs blocker surfaced while repairing #17: clarify deterministic setup and QA",
        body=(
            "<!-- precision-squad:docs-remediation -->\n\n"
            "## Context\nA\n\n"
            "## Why This Is Separate\nB\n\n"
            "## Blocker\nC\n\n"
            "## Reason Codes\n- docs_setup_prerequisites_ambiguous\n\n"
            "## Desired Outcome\nD\n"
            + ("extra text\n" * 300)
        ),
        labels=(),
        html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/18",
    )

    intake = build_issue_intake(issue)

    assert intake.assessment.status == "runnable"
    assert intake.assessment.reason_codes == ()
