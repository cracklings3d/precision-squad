"""Tests for structured docs-remediation finding identity and scope."""

from __future__ import annotations

from precision_squad.docs_remediation import (
    docs_baseline_findings_marker,
    docs_blocker_fingerprint,
    docs_target_findings_marker,
    evaluate_docs_remediation_scope,
    normalize_docs_findings,
)


def test_normalize_docs_findings_dedupes_and_sorts_stably() -> None:
    findings = [
        {
            "rule_id": "docs_qa_command_missing",
            "source_path": "README.md",
            "section_key": "Testing",
            "subject_key": "qa-command",
        },
        {
            "rule_id": "docs_qa_command_missing",
            "source_path": "readme.md",
            "section_key": "testing",
            "subject_key": "qa-command",
        },
        {
            "rule_id": "docs_setup_command_present",
            "source_path": "README.md",
            "section_key": "Setup",
            "subject_key": "setup-command",
        },
    ]

    normalized = normalize_docs_findings(findings)

    assert normalized == [
        {
            "rule_id": "docs_qa_command_missing",
            "source_path": "readme.md",
            "section_key": "testing",
            "subject_key": "qa-command",
        },
        {
            "rule_id": "docs_setup_command_present",
            "source_path": "readme.md",
            "section_key": "setup",
            "subject_key": "setup-command",
        },
    ]


def test_docs_blocker_fingerprint_is_order_independent() -> None:
    left = [
        {
            "rule_id": "docs_setup_prerequisite_version_pinned",
            "source_path": "readme.md",
            "section_key": "windows-system-dependencies",
            "subject_key": "gtk3-runtime",
        },
        {
            "rule_id": "docs_setup_prerequisite_verification_present",
            "source_path": "readme.md",
            "section_key": "windows-system-dependencies",
            "subject_key": "gtk3-runtime",
        },
    ]
    right = list(reversed(left))

    assert docs_blocker_fingerprint(left) == docs_blocker_fingerprint(right)


def test_docs_blocker_fingerprint_separates_distinct_subjects() -> None:
    gtk_finding = [
        {
            "rule_id": "docs_setup_prerequisite_version_pinned",
            "source_path": "readme.md",
            "section_key": "windows-system-dependencies",
            "subject_key": "gtk3-runtime",
        }
    ]
    poetry_finding = [
        {
            "rule_id": "docs_setup_prerequisite_version_pinned",
            "source_path": "readme.md",
            "section_key": "windows-system-dependencies",
            "subject_key": "poetry",
        }
    ]

    assert docs_blocker_fingerprint(gtk_finding) != docs_blocker_fingerprint(poetry_finding)


def test_docs_blocker_fingerprint_separates_distinct_sections_for_same_rule() -> None:
    first = [
        {
            "rule_id": "docs_environment_assumptions_explicit",
            "source_path": "readme.md",
            "section_key": "windows-system-dependencies",
            "subject_key": "environment-mutation",
        }
    ]
    second = [
        {
            "rule_id": "docs_environment_assumptions_explicit",
            "source_path": "readme.md",
            "section_key": "macos-system-dependencies",
            "subject_key": "environment-mutation",
        }
    ]

    assert docs_blocker_fingerprint(first) != docs_blocker_fingerprint(second)


def test_evaluate_docs_remediation_scope_allows_baseline_findings_to_remain() -> None:
    target = [
        {
            "rule_id": "docs_setup_prerequisite_version_pinned",
            "source_path": "readme.md",
            "section_key": "windows-system-dependencies",
            "subject_key": "gtk3-runtime",
        }
    ]
    baseline = [
        {
            "rule_id": "docs_qa_command_missing",
            "source_path": "readme.md",
            "section_key": "testing",
            "subject_key": "qa-command",
        }
    ]
    issue_body = (
        docs_target_findings_marker(target)
        + "\n"
        + docs_baseline_findings_marker(baseline)
    )

    scope = evaluate_docs_remediation_scope(issue_body, baseline)

    assert scope.unresolved_target_findings == ()
    assert scope.baseline_remaining_findings == tuple(baseline)
    assert scope.new_findings == ()


def test_evaluate_docs_remediation_scope_detects_new_findings() -> None:
    target = [
        {
            "rule_id": "docs_setup_prerequisite_version_pinned",
            "source_path": "readme.md",
            "section_key": "windows-system-dependencies",
            "subject_key": "gtk3-runtime",
        }
    ]
    current = [
        {
            "rule_id": "docs_environment_assumptions_explicit",
            "source_path": "readme.md",
            "section_key": "windows-system-dependencies",
            "subject_key": "environment-mutation",
        }
    ]
    scope = evaluate_docs_remediation_scope(docs_target_findings_marker(target), current)

    assert scope.unresolved_target_findings == ()
    assert scope.new_findings == tuple(current)
