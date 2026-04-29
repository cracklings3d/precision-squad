"""Shared documentation policy rules for docs-first execution."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def _load_checklist() -> dict[str, Any]:
    path = Path(__file__).with_name("data") / "docs_checklist.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("docs checklist must be a JSON object")
    return payload


CHECKLIST = _load_checklist()
DOC_SOURCE_CANDIDATES = tuple(str(item) for item in CHECKLIST["doc_source_candidates"])
SETUP_SECTION_HEADINGS = tuple(str(item) for item in CHECKLIST["setup_section_headings"])
TEST_SECTION_HEADINGS = tuple(str(item) for item in CHECKLIST["test_section_headings"])
PREREQUISITE_SECTION_HEADINGS = tuple(str(item) for item in CHECKLIST["prerequisite_section_headings"])
MANUAL_PREREQUISITE_SIGNALS = tuple(str(item) for item in CHECKLIST["manual_prerequisite_signals"])
ENVIRONMENT_ASSUMPTION_SIGNALS = tuple(str(item) for item in CHECKLIST["environment_assumption_signals"])
DOC_POLICY_RULES: tuple[dict[str, Any], ...] = tuple(
    dict(rule) for rule in CHECKLIST["rules"] if isinstance(rule, dict)
)


def questions_for_violations(violations: tuple[str, ...]) -> tuple[str, ...]:
    questions: list[str] = []
    for rule in DOC_POLICY_RULES:
        if rule["code"] in violations:
            questions.append(str(rule["question"]))
    return tuple(dict.fromkeys(questions))


def requirements_for_violations(violations: tuple[str, ...]) -> tuple[str, ...]:
    requirements: list[str] = []
    for rule in DOC_POLICY_RULES:
        if rule["code"] in violations:
            requirements.append(str(rule["requirement"]))
    return tuple(dict.fromkeys(requirements))
