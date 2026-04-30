"""Tests for shared docs policy helpers."""

from __future__ import annotations

from precision_squad.docs_policy import (
    DOC_POLICY_RULES,
    DOC_SOURCE_CANDIDATES,
    questions_for_violations,
    requirements_for_violations,
)


def test_doc_source_candidates_prioritize_readme_before_contributing() -> None:
    assert DOC_SOURCE_CANDIDATES[0] == "README.md"
    assert DOC_SOURCE_CANDIDATES.index("README.md") < DOC_SOURCE_CANDIDATES.index("CONTRIBUTING.md")


def test_questions_for_violations_preserves_policy_order_and_deduplicates() -> None:
    violations = (
        "docs_qa_command_present",
        "docs_entrypoint_present",
        "docs_qa_command_present",
    )

    assert questions_for_violations(violations) == (
        "Where should a newcomer start reading?",
        "What exact QA command should a newcomer run after making a change?",
    )


def test_requirements_for_violations_preserves_policy_order_and_deduplicates() -> None:
    violations = (
        "docs_commands_explained",
        "docs_setup_command_present",
        "docs_setup_command_present",
    )

    assert requirements_for_violations(violations) == (
        "State one canonical local setup command in the docs.",
        "Briefly explain the setup and QA commands so a newcomer understands what they are for.",
    )


def test_docs_policy_includes_blocking_prerequisite_and_environment_rules() -> None:
    codes = {str(rule["code"]) for rule in DOC_POLICY_RULES}

    assert "docs_setup_prerequisite_manual_only" in codes
    assert "docs_setup_prerequisite_version_pinned" in codes
    assert "docs_setup_prerequisite_source_unambiguous" in codes
    assert "docs_environment_assumptions_explicit" in codes
