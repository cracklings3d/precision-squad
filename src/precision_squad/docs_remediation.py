"""Helpers for docs-remediation issue detection and deduplication."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DOCS_REMEDIATION_MARKER = "<!-- precision-squad:docs-remediation -->"
DOCS_BLOCKER_FINGERPRINT_PATTERN = re.compile(
    r"<!-- precision-squad:blocker-fingerprint:(?P<value>[a-f0-9]{12,64}) -->"
)
DOCS_BLOCKER_FINDINGS_PATTERN = re.compile(
    r"<!-- precision-squad:blocker-findings:(?P<value>.+?) -->"
)
DOCS_TARGET_FINDINGS_PATTERN = re.compile(
    r"<!-- precision-squad:target-findings:(?P<value>.+?) -->"
)
DOCS_BASELINE_FINDINGS_PATTERN = re.compile(
    r"<!-- precision-squad:baseline-findings:(?P<value>.+?) -->"
)
LEGACY_DOCS_REMEDIATION_TITLE_PREFIX = "Docs blocker surfaced while repairing #"


@dataclass(frozen=True, slots=True)
class DocsRemediationScope:
    """Tracked target/baseline/current findings for a docs-remediation issue."""

    target_findings: tuple[dict[str, str], ...]
    baseline_findings: tuple[dict[str, str], ...]
    current_findings: tuple[dict[str, str], ...]
    unresolved_target_findings: tuple[dict[str, str], ...]
    baseline_remaining_findings: tuple[dict[str, str], ...]
    new_findings: tuple[dict[str, str], ...]


def normalize_docs_findings(findings: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Normalize and sort docs findings for stable hashing and comparison."""
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for finding in findings:
        rule_id = str(finding.get("rule_id", "")).strip()
        source_path = str(finding.get("source_path", "")).strip().lower()
        section_key = str(finding.get("section_key", "")).strip().lower()
        subject_key = str(finding.get("subject_key", "")).strip().lower()
        if not rule_id or not source_path or not section_key:
            continue
        key = (rule_id, source_path, section_key, subject_key)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "rule_id": rule_id,
                "source_path": source_path,
                "section_key": section_key,
                "subject_key": subject_key,
            }
        )
    normalized.sort(
        key=lambda item: (
            item["rule_id"],
            item["source_path"],
            item["section_key"],
            item["subject_key"],
        )
    )
    return normalized


def docs_blocker_fingerprint(findings: Sequence[dict[str, str]]) -> str:
    """Return a stable fingerprint for one docs blocker finding set."""
    normalized = normalize_docs_findings(findings)
    payload = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def docs_blocker_fingerprint_marker(fingerprint: str) -> str:
    """Render the hidden HTML marker for a blocker fingerprint."""
    return f"<!-- precision-squad:blocker-fingerprint:{fingerprint} -->"


def docs_blocker_findings_marker(findings: Sequence[dict[str, str]]) -> str:
    """Render the hidden HTML marker for serialized blocker findings."""
    payload = json.dumps(
        normalize_docs_findings(findings),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"<!-- precision-squad:blocker-findings:{payload} -->"


def docs_target_findings_marker(findings: Sequence[dict[str, str]]) -> str:
    """Render the hidden HTML marker for tracked target findings."""
    payload = json.dumps(
        normalize_docs_findings(findings),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"<!-- precision-squad:target-findings:{payload} -->"


def docs_baseline_findings_marker(findings: Sequence[dict[str, str]]) -> str:
    """Render the hidden HTML marker for tracked baseline findings."""
    payload = json.dumps(
        normalize_docs_findings(findings),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"<!-- precision-squad:baseline-findings:{payload} -->"


def extract_docs_blocker_fingerprint(body: str) -> str | None:
    """Extract the fingerprint marker from a docs-remediation issue body."""
    match = DOCS_BLOCKER_FINGERPRINT_PATTERN.search(body)
    if match is None:
        return None
    return match.group("value")


def extract_docs_blocker_findings(body: str) -> list[dict[str, str]]:
    """Extract serialized blocker findings from a docs-remediation issue body."""
    match = DOCS_BLOCKER_FINDINGS_PATTERN.search(body)
    if match is None:
        return []
    try:
        payload = json.loads(match.group("value"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return normalize_docs_findings(
        [item for item in payload if isinstance(item, dict)]
    )


def extract_docs_target_findings(body: str) -> list[dict[str, str]]:
    """Extract tracked target findings from a docs-remediation issue body."""
    extracted = _extract_serialized_findings(DOCS_TARGET_FINDINGS_PATTERN, body)
    if extracted:
        return extracted
    return extract_docs_blocker_findings(body)


def extract_docs_baseline_findings(body: str) -> list[dict[str, str]]:
    """Extract tracked baseline findings from a docs-remediation issue body."""
    return _extract_serialized_findings(DOCS_BASELINE_FINDINGS_PATTERN, body)


def load_contract_findings(artifact_dir: str | Path | None) -> list[dict[str, str]]:
    """Load normalized findings from a contract artifact directory."""
    if artifact_dir is None:
        return []
    path = Path(artifact_dir)
    contract_path = path / "contract.json"
    if not contract_path.exists():
        return []
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        return []
    return normalize_docs_findings(
        [item for item in raw_findings if isinstance(item, dict)]
    )


def evaluate_docs_remediation_scope(
    issue_body: str, current_findings: Sequence[dict[str, str]]
) -> DocsRemediationScope:
    """Compare current findings to tracked target and baseline finding sets."""
    current = normalize_docs_findings(current_findings)
    target = extract_docs_target_findings(issue_body)
    baseline = extract_docs_baseline_findings(issue_body)
    if not target and current:
        # Legacy remediation issues without explicit scope still behave like all-or-nothing fixes.
        target = current

    unresolved_target = [finding for finding in target if finding in current]
    baseline_remaining = [finding for finding in baseline if finding in current]
    new_findings = [
        finding
        for finding in current
        if finding not in target and finding not in baseline
    ]

    return DocsRemediationScope(
        target_findings=tuple(target),
        baseline_findings=tuple(baseline),
        current_findings=tuple(current),
        unresolved_target_findings=tuple(unresolved_target),
        baseline_remaining_findings=tuple(baseline_remaining),
        new_findings=tuple(new_findings),
    )


def summarize_docs_findings(findings: Sequence[dict[str, str]], limit: int = 3) -> str:
    """Render a compact human-readable summary of findings."""
    items = []
    for finding in list(findings)[:limit]:
        items.append(
            f"{finding['rule_id']} @ {finding['source_path']}::"
            f"{finding['section_key']}::{finding['subject_key']}"
        )
    return "; ".join(items)


def is_docs_remediation_title_or_body(title: str, body: str) -> bool:
    """Return whether the issue exists to remediate repo documentation blockers."""
    return (
        DOCS_REMEDIATION_MARKER in body
        or title.strip().startswith(LEGACY_DOCS_REMEDIATION_TITLE_PREFIX)
    )


def _extract_serialized_findings(
    pattern: re.Pattern[str], body: str
) -> list[dict[str, str]]:
    match = pattern.search(body)
    if match is None:
        return []
    try:
        payload = json.loads(match.group("value"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return normalize_docs_findings(
        [item for item in payload if isinstance(item, dict)]
    )
