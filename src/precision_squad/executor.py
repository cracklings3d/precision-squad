"""Executor seam for docs-first local issue execution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .docs_policy import (
    DOC_SOURCE_CANDIDATES,
    ENVIRONMENT_ASSUMPTION_SIGNALS,
    MANUAL_PREREQUISITE_SIGNALS,
    PREREQUISITE_SECTION_HEADINGS,
    SETUP_SECTION_HEADINGS,
    TEST_SECTION_HEADINGS,
    questions_for_violations,
    requirements_for_violations,
)
from .models import ExecutionContract, ExecutionResult, IssueIntake, RunRecord

COMMAND_PATTERN = re.compile(r"`([^`\n]+)`")
SHELL_PREFIX_PATTERN = re.compile(r"^\s*(?:\$|PS>)\s*")
URL_PATTERN = re.compile(r"https?://\S+")
VERSION_PATTERN = re.compile(r"\b\d+(?:\.\d+){1,3}\b")


@dataclass(frozen=True, slots=True)
class _DocExtraction:
    source_path: str
    setup_commands: tuple[str, ...]
    qa_commands: tuple[str, ...]
    notes: tuple[str, ...]
    manual_prerequisites: tuple[str, ...]
    environment_assumptions: tuple[str, ...]
    verification_gaps: tuple[str, ...]
    findings: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class _DocsBlockResolution:
    status: Literal["missing_docs"]
    summary: str
    detail_code: str


class Executor:
    """Abstract execution boundary for a persisted run."""

    name = "executor"

    def execute(self, intake: IssueIntake, run_record: RunRecord, run_dir: Path) -> ExecutionResult:
        raise NotImplementedError


class DocsFirstExecutor(Executor):
    """Build a local execution contract from documented repo instructions."""

    name = "docs"

    def __init__(self, *, repo_path: Path) -> None:
        self.repo_path = repo_path

    def execute(self, intake: IssueIntake, run_record: RunRecord, run_dir: Path) -> ExecutionResult:
        del intake, run_record

        if not self.repo_path.exists():
            return ExecutionResult(
                status="failed_infra",
                executor_name=self.name,
                summary=f"Target repository path does not exist: {self.repo_path}",
                detail_codes=("target_repo_missing",),
            )

        if not self.repo_path.is_dir():
            return ExecutionResult(
                status="failed_infra",
                executor_name=self.name,
                summary=f"Target repository path is not a directory: {self.repo_path}",
                detail_codes=("target_repo_not_directory",),
            )

        contract_dir = run_dir / "execution-contract"
        contract_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "executor.stdout.log"
        stderr_path = run_dir / "executor.stderr.log"

        doc_sources = _resolve_doc_sources(self.repo_path)
        if not doc_sources:
            violations = (
                "docs_entrypoint_present",
                "docs_setup_command_present",
                "docs_qa_command_present",
            )
            summary = (
                "Could not find project-facing documentation for this repository. A newcomer would "
                "immediately ask: where are the setup instructions, and what exact command proves "
                "the issue is fixed? Add a README or equivalent contributor guide "
                "before running repair."
            )
            contract = ExecutionContract(
                source_path=None,
                setup_commands=(),
                qa_command=None,
                notes=(),
                questions=questions_for_violations(violations),
                violations=violations,
                findings=_missing_entrypoint_findings(),
            )
            _write_contract_artifacts(contract_dir, contract, [])
            _write_doc_fix_prompt(
                contract_dir=contract_dir,
                repo_path=self.repo_path,
                summary=summary,
                status="missing_docs",
                violations=violations,
            )
            stdout_path.write_text(
                json.dumps(_contract_payload(contract), indent=2) + "\n",
                encoding="utf-8",
            )
            stderr_path.write_text(summary + "\n", encoding="utf-8")
            return ExecutionResult(
                status="missing_docs",
                executor_name=self.name,
                summary=summary,
                detail_codes=("docs_missing",),
                artifact_dir=str(contract_dir),
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )

        extractions = [_extract_from_doc(path) for path in doc_sources]
        contract, ambiguity_summary = _build_execution_contract(extractions)
        _write_contract_artifacts(contract_dir, contract, doc_sources)
        stdout_path.write_text(
            json.dumps(_contract_payload(contract), indent=2) + "\n",
            encoding="utf-8",
        )

        if ambiguity_summary is not None:
            _write_doc_fix_prompt(
                contract_dir=contract_dir,
                repo_path=self.repo_path,
                summary=ambiguity_summary,
                status="ambiguous_docs",
                violations=contract.violations,
            )
            stderr_path.write_text(ambiguity_summary + "\n", encoding="utf-8")
            return ExecutionResult(
                status="ambiguous_docs",
                executor_name=self.name,
                summary=ambiguity_summary,
                detail_codes=("docs_ambiguous",),
                artifact_dir=str(contract_dir),
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )

        if contract.violations:
            resolution = _classify_missing_contract_parts(contract)
            _write_doc_fix_prompt(
                contract_dir=contract_dir,
                repo_path=self.repo_path,
                summary=resolution.summary,
                status=resolution.status,
                violations=contract.violations,
            )
            stderr_path.write_text(resolution.summary + "\n", encoding="utf-8")
            return ExecutionResult(
                status=resolution.status,
                executor_name=self.name,
                summary=resolution.summary,
                detail_codes=(resolution.detail_code,),
                artifact_dir=str(contract_dir),
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )

        stderr_path.write_text("", encoding="utf-8")
        return ExecutionResult(
            status="completed",
            executor_name=self.name,
            summary="Repository documentation yielded an explicit local setup and QA contract.",
            detail_codes=("docs_contract_ready",),
            artifact_dir=str(contract_dir),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )


def _resolve_doc_sources(repo_path: Path) -> list[Path]:
    sources: list[Path] = []
    for candidate in DOC_SOURCE_CANDIDATES:
        path = repo_path / candidate
        if path.exists() and path.is_file():
            sources.append(path)
    return sources


def _extract_from_doc(source_path: Path) -> _DocExtraction:
    text = source_path.read_text(encoding="utf-8", errors="ignore")
    sections = _split_markdown_sections(text)
    setup_commands: list[str] = []
    qa_commands: list[str] = []
    notes: list[str] = []
    manual_prerequisites: list[str] = []
    environment_assumptions: list[str] = []
    verification_gaps: list[str] = []
    findings: list[dict[str, str]] = []

    setup_sections = [
        body
        for heading, body in sections
        if heading is not None and heading.lower() in SETUP_SECTION_HEADINGS
    ]
    test_sections = [
        body
        for heading, body in sections
        if heading is not None and heading.lower() in TEST_SECTION_HEADINGS
    ]
    prerequisite_sections = [
        (heading, body)
        for heading, body in sections
        if heading is not None and heading.lower() in PREREQUISITE_SECTION_HEADINGS
    ]

    for body in setup_sections:
        setup_commands.extend(_extract_commands(body))
    for body in test_sections:
        qa_commands.extend(_extract_qa_commands(_extract_commands(body)))

    if setup_sections and setup_commands:
        notes.append(f"{source_path.name} provides documented setup commands.")
    if test_sections and qa_commands:
        notes.append(f"{source_path.name} provides documented QA commands.")

    for heading, body in prerequisite_sections:
        source_key = _normalize_path_key(source_path.name)
        section_key = _normalize_section_key(heading)
        subject_key = _detect_subject_key(body)
        signals = _extract_manual_prerequisite_signals(body)
        prerequisite_commands = _extract_prerequisite_commands(body)
        if signals:
            manual_prerequisites.extend(
                f"{source_path.name}::{heading}: {signal}" for signal in signals
            )
        if signals and not prerequisite_commands:
            findings.append(
                _finding(
                    rule_id="docs_setup_prerequisite_manual_only",
                    source_path=source_key,
                    section_key=section_key,
                    subject_key=subject_key,
                )
            )
        assumptions = _extract_environment_assumptions(body)
        if assumptions:
            environment_assumptions.extend(
                f"{source_path.name}::{heading}: {assumption}" for assumption in assumptions
            )
        if assumptions and not _environment_assumptions_are_explicit(body):
            findings.append(
                _finding(
                    rule_id="docs_environment_assumptions_explicit",
                    source_path=source_key,
                    section_key=section_key,
                    subject_key=subject_key,
                )
            )
        if signals and not prerequisite_commands and not _extract_commands(body):
            verification_gaps.append(
                f"{source_path.name}::{heading}: prerequisite guidance is prose-only "
                "and does not include an exact executable install or verification "
                "command."
            )
            findings.append(
                _finding(
                    rule_id="docs_setup_prerequisite_verification_present",
                    source_path=source_key,
                    section_key=section_key,
                    subject_key=subject_key,
                )
            )
        if signals and not _contains_pinned_version(body):
            verification_gaps.append(
                f"{source_path.name}::{heading}: prerequisite guidance does not "
                "specify an exact version, release, or channel."
            )
            findings.append(
                _finding(
                    rule_id="docs_setup_prerequisite_version_pinned",
                    source_path=source_key,
                    section_key=section_key,
                    subject_key=subject_key,
                )
            )
        if signals and _source_is_ambiguous(body):
            verification_gaps.append(
                f"{source_path.name}::{heading}: prerequisite guidance does not say "
                "whether to use a release artifact, package manager, or source "
                "build."
            )
            findings.append(
                _finding(
                    rule_id="docs_setup_prerequisite_source_unambiguous",
                    source_path=source_key,
                    section_key=section_key,
                    subject_key=subject_key,
                )
            )
        if assumptions and not _extract_commands(body):
            verification_gaps.append(
                f"{source_path.name}::{heading}: environment assumptions are "
                "described, but there is no exact command that proves they took "
                "effect in the active shell."
            )
            findings.append(
                _finding(
                    rule_id="docs_environment_mutation_verification_present",
                    source_path=source_key,
                    section_key=section_key,
                    subject_key=subject_key,
                )
            )

    return _DocExtraction(
        source_path=str(source_path),
        setup_commands=tuple(dict.fromkeys(setup_commands)),
        qa_commands=tuple(dict.fromkeys(qa_commands)),
        notes=tuple(notes),
        manual_prerequisites=tuple(dict.fromkeys(manual_prerequisites)),
        environment_assumptions=tuple(dict.fromkeys(environment_assumptions)),
        verification_gaps=tuple(dict.fromkeys(verification_gaps)),
        findings=tuple(_dedupe_findings(findings)),
    )


def _build_execution_contract(
    extractions: list[_DocExtraction],
) -> tuple[ExecutionContract, str | None]:
    setup_variants = {
        commands
        for extraction in extractions
        for commands in ([extraction.setup_commands] if extraction.setup_commands else [])
    }
    qa_variants = {command for extraction in extractions for command in extraction.qa_commands}
    notes = tuple(note for extraction in extractions for note in extraction.notes)
    source_paths = tuple(extraction.source_path for extraction in extractions)
    manual_prerequisites = tuple(
        item for extraction in extractions for item in extraction.manual_prerequisites
    )
    environment_assumptions = tuple(
        item for extraction in extractions for item in extraction.environment_assumptions
    )
    verification_gaps = tuple(
        item for extraction in extractions for item in extraction.verification_gaps
    )
    findings = [finding for extraction in extractions for finding in extraction.findings]

    violations: list[str] = []
    ambiguity_summary = None
    if len(setup_variants) > 1:
        violations.append("docs_setup_command_unambiguous")
        findings.append(
            _finding(
                rule_id="docs_setup_command_unambiguous",
                source_path=_first_source_name(source_paths),
                section_key="setup",
                subject_key="setup-path",
            )
        )
        ambiguity_summary = (
            "The documentation describes multiple competing setup paths. A newcomer would ask: "
            "which install command is the canonical one for this repository, and which path should "
            "this workflow trust? Consolidate the docs before running repair."
        )
    if len(qa_variants) > 1:
        violations.append("docs_qa_command_unambiguous")
        findings.append(
            _finding(
                rule_id="docs_qa_command_unambiguous",
                source_path=_first_source_name(source_paths),
                section_key="testing",
                subject_key="qa-command",
            )
        )
        if ambiguity_summary is None:
            ambiguity_summary = (
                "The documentation describes multiple competing QA commands. A newcomer would ask: "
                "which command is the canonical proof that a fix works, and which "
                "test path should this "
                "workflow trust? Consolidate the docs before running repair."
            )

    setup_commands = next(iter(setup_variants)) if len(setup_variants) == 1 else ()
    qa_command = next(iter(qa_variants)) if len(qa_variants) == 1 else None
    if not source_paths:
        violations.append("docs_entrypoint_present")
    if not setup_commands:
        violations.append("docs_setup_command_present")
        findings.append(
            _finding(
                rule_id="docs_setup_command_present",
                source_path=_first_source_name(source_paths),
                section_key="setup",
                subject_key="setup-command",
            )
        )
    if qa_command is None:
        violations.append("docs_qa_command_present")
        findings.append(
            _finding(
                rule_id="docs_qa_command_present",
                source_path=_first_source_name(source_paths),
                section_key="testing",
                subject_key="qa-command",
            )
        )
    if notes and (setup_commands or qa_command):
        pass
    else:
        violations.append("docs_commands_explained")
        findings.append(
            _finding(
                rule_id="docs_commands_explained",
                source_path=_first_source_name(source_paths),
                section_key="docs",
                subject_key="command-explanation",
            )
        )
    if any(finding["rule_id"] == "docs_setup_prerequisite_manual_only" for finding in findings):
        violations.append("docs_setup_prerequisite_manual_only")
    if manual_prerequisites and any(
        "does not specify an exact version" in gap for gap in verification_gaps
    ):
        violations.append("docs_setup_prerequisite_version_pinned")
    if manual_prerequisites and any(
        "does not say whether to use a release artifact, package manager, or source build" in gap
        for gap in verification_gaps
    ):
        violations.append("docs_setup_prerequisite_source_unambiguous")
    if manual_prerequisites and any(
        "does not include an exact executable install or verification command" in gap
        for gap in verification_gaps
    ):
        violations.append("docs_setup_prerequisite_verification_present")
    if any(
        finding["rule_id"] == "docs_environment_assumptions_explicit" for finding in findings
    ):
        violations.append("docs_environment_assumptions_explicit")
    if any(
        "there is no exact command that proves they took effect"
        in gap
        for gap in verification_gaps
    ):
        violations.append("docs_environment_mutation_verification_present")

    source_path = source_paths[0] if len(source_paths) == 1 else ", ".join(source_paths)
    contract = ExecutionContract(
        source_path=source_path if source_paths else None,
        setup_commands=setup_commands,
        qa_command=qa_command,
        notes=notes,
        questions=questions_for_violations(tuple(dict.fromkeys(violations))),
        violations=tuple(dict.fromkeys(violations)),
        manual_prerequisites=tuple(dict.fromkeys(manual_prerequisites)),
        environment_assumptions=tuple(dict.fromkeys(environment_assumptions)),
        verification_gaps=tuple(dict.fromkeys(verification_gaps)),
        findings=tuple(_dedupe_findings(findings)),
    )
    return contract, ambiguity_summary


def _classify_missing_contract_parts(
    contract: ExecutionContract,
) -> _DocsBlockResolution:
    if not contract.setup_commands and contract.qa_command is None:
        return _DocsBlockResolution(
            status="missing_docs",
            summary=(
                "The docs do not tell a newcomer how to set the project up or how to verify a fix. "
                "Document both the install path and the QA command before running repair."
            ),
            detail_code="docs_contract_incomplete",
        )
    prerequisite_or_environment_violations = {
        "docs_setup_prerequisite_manual_only",
        "docs_setup_prerequisite_version_pinned",
        "docs_setup_prerequisite_source_unambiguous",
        "docs_setup_prerequisite_verification_present",
        "docs_environment_assumptions_explicit",
        "docs_environment_mutation_verification_present",
    }
    if any(code in prerequisite_or_environment_violations for code in contract.violations):
        findings = list(
            contract.manual_prerequisites
            + contract.environment_assumptions
            + contract.verification_gaps
        )
        finding_summary = " ".join(findings[:3])
        return _DocsBlockResolution(
            status="missing_docs",
            summary=(
                "The docs describe human-readable prerequisites or environment "
                "assumptions, but they do not reduce that uncertainty into one "
                "deterministic automation-safe setup path. "
                f"Detected findings: {finding_summary}"
            ),
            detail_code="docs_setup_prerequisites_ambiguous",
        )
    if not contract.setup_commands:
        return _DocsBlockResolution(
            status="missing_docs",
            summary=(
                "Could not find a documented local setup command in the repository "
                "instructions. A newcomer would ask: how am I supposed to install "
                "this project, which package manager should I use, and what is the "
                "first command I should run in a clean checkout? Document that "
                "explicitly "
                "before asking the repair workflow to proceed."
            ),
            detail_code="docs_setup_command_missing",
        )
    return _DocsBlockResolution(
        status="missing_docs",
        summary=(
            "Could not find a documented QA command for this repository. A "
            "newcomer would ask: after making a fix, what exact command should I "
            "run in PowerShell to prove the change works, and which test or test "
            "subset is the intended signal for this issue? Document that command "
            "explicitly before asking the repair workflow to proceed."
        ),
        detail_code="docs_qa_command_missing",
    )


def _split_markdown_sections(text: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if current_heading is not None or current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line.lstrip("#").strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_heading is not None or current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return sections


def _extract_commands(section_text: str) -> list[str]:
    commands: list[str] = []
    for raw_line in section_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            continue
        if stripped.startswith("-"):
            stripped = stripped[1:].strip()
        stripped = SHELL_PREFIX_PATTERN.sub("", stripped)
        inline_match = COMMAND_PATTERN.search(stripped)
        candidate = inline_match.group(1).strip() if inline_match else stripped
        if _looks_like_command(candidate):
            commands.append(candidate)
    return commands


def _extract_qa_commands(commands: list[str]) -> list[str]:
    qa_commands: list[str] = []
    for command in commands:
        lowered = command.lower()
        if lowered.startswith(
            ("python -m pytest", "pytest ", "uv run pytest ", "poetry run pytest ")
        ):
            qa_commands.append(command)
    return qa_commands


def _extract_prerequisite_commands(section_text: str) -> list[str]:
    commands: list[str] = []
    for command in _extract_commands(section_text):
        lowered = command.lower()
        if lowered.startswith(
            (
                "winget ",
                "choco ",
                "scoop ",
                "curl ",
                "Invoke-WebRequest ".lower(),
                "iwr ",
                "Start-Process ".lower(),
                ".\\",
            )
        ):
            commands.append(command)
    return commands


def _looks_like_command(text: str) -> bool:
    lowered = text.lower()
    return lowered.startswith(
        (
            "python ",
            "python -m ",
            "py ",
            "pip ",
            "uv ",
            "poetry ",
            "pytest ",
            "winget ",
            "choco ",
            "scoop ",
            "curl ",
            "invoke-webrequest ",
            "iwr ",
            "start-process ",
            ".\\",
        )
    )


def _contract_payload(contract: ExecutionContract) -> dict[str, object]:
    return {
        "source_path": contract.source_path,
        "setup_commands": list(contract.setup_commands),
        "qa_command": contract.qa_command,
        "notes": list(contract.notes),
        "questions": list(contract.questions),
        "violations": list(contract.violations),
        "manual_prerequisites": list(contract.manual_prerequisites),
        "environment_assumptions": list(contract.environment_assumptions),
        "verification_gaps": list(contract.verification_gaps),
        "findings": list(contract.findings),
    }


def _write_contract_artifacts(
    contract_dir: Path, contract: ExecutionContract, source_paths: list[Path]
) -> None:
    (contract_dir / "contract.json").write_text(
        json.dumps(_contract_payload(contract), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    snapshot_chunks: list[str] = []
    for source_path in source_paths:
        snapshot_chunks.append(
            f"# Source: {source_path.as_posix()}\n\n"
            + source_path.read_text(encoding="utf-8", errors="ignore").strip()
            + "\n"
        )
    (contract_dir / "README.snapshot.md").write_text("\n\n".join(snapshot_chunks), encoding="utf-8")


def _write_doc_fix_prompt(
    *,
    contract_dir: Path,
    repo_path: Path,
    summary: str,
    status: str,
    violations: tuple[str, ...],
) -> None:
    requirements = requirements_for_violations(violations)
    requirement_lines = "\n".join(f"- {item}" for item in requirements) or "- none"
    question_lines = (
        "\n".join(f"- {item}" for item in questions_for_violations(violations)) or "- none"
    )
    violation_lines = "\n".join(f"- {item}" for item in violations) or "- none"
    prompt = "\n".join(
        [
            "Create or update the repository documentation so a newcomer can run "
            "this project locally.",
            f"Repository: {repo_path}",
            f"Docs status: {status}",
            f"Problem summary: {summary}",
            "Policy violations:",
            violation_lines,
            "Requirements:",
            requirement_lines,
            "Questions the docs must answer:",
            question_lines,
            "Output expectations:",
            "- Update README.md or CONTRIBUTING.md with one canonical setup path "
            "and one canonical QA path.",
            "- Keep the change focused on documentation only.",
            "- Do not invent multiple alternatives unless the docs clearly "
            "designate one as canonical.",
            "- Do not use ambiguous wording such as `latest`, `stable`, "
            "`current`, or `recent` when the checklist requires a deterministic "
            "prerequisite version, release, or channel.",
            "- If a prerequisite is external, state whether the canonical source "
            "is a release artifact, package manager, or source build.",
            "- If the docs mention an installer or environment mutation, include "
            "an exact post-install verification command that a newcomer can run "
            "in the active shell.",
            "- If you cannot document an exact deterministic prerequisite path "
            "yet, do not soften the requirement with prose; make the missing "
            "requirement explicit in the docs.",
        ]
    )
    (contract_dir / "docs-fix-prompt.txt").write_text(prompt + "\n", encoding="utf-8")


def _extract_manual_prerequisite_signals(section_text: str) -> list[str]:
    findings: list[str] = []
    lowered = section_text.lower()
    if any(signal in lowered for signal in MANUAL_PREREQUISITE_SIGNALS):
        for line in section_text.splitlines():
            stripped = line.strip()
            lowered_line = stripped.lower()
            if not stripped:
                continue
            if any(signal in lowered_line for signal in MANUAL_PREREQUISITE_SIGNALS):
                findings.append(stripped)
    return findings


def _extract_environment_assumptions(section_text: str) -> list[str]:
    findings: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if not stripped:
            continue
        if any(signal in lowered for signal in ENVIRONMENT_ASSUMPTION_SIGNALS):
            findings.append(stripped)
    return findings


def _environment_assumptions_are_explicit(section_text: str) -> bool:
    lowered = section_text.lower()
    explicit_markers = (
        "environment assumptions",
        "this setup path relies on",
        "must be on the system path",
        "required because",
        "current session",
        "active shell",
    )
    return any(marker in lowered for marker in explicit_markers)


def _contains_pinned_version(section_text: str) -> bool:
    if VERSION_PATTERN.search(section_text):
        return True
    lowered = section_text.lower()
    return any(marker in lowered for marker in ("latest", "stable", "lts"))


def _source_is_ambiguous(section_text: str) -> bool:
    lowered = section_text.lower()
    mentions_url = URL_PATTERN.search(section_text) is not None
    mentions_source = "source" in lowered or "build" in lowered
    mentions_package_manager = any(
        token in lowered for token in ("winget", "choco", "scoop", "apt", "brew")
    )
    mentions_release_artifact = any(
        token in lowered
        for token in ("release artifact", "release installer", "download the release")
    )
    if mentions_url and not (
        mentions_source or mentions_package_manager or mentions_release_artifact
    ):
        return True
    if mentions_source and not mentions_release_artifact and not mentions_package_manager:
        return True
    return False


def _normalize_path_key(path_text: str) -> str:
    return path_text.replace("\\", "/").strip().lower()


def _normalize_section_key(heading: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", heading.strip().lower()).strip("-")
    return normalized or "unknown-section"


def _normalize_subject_key(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return normalized or "docs-subject"


def _finding(
    *, rule_id: str, source_path: str, section_key: str, subject_key: str
) -> dict[str, str]:
    return {
        "rule_id": rule_id,
        "source_path": _normalize_path_key(source_path),
        "section_key": section_key,
        "subject_key": subject_key,
    }


def _dedupe_findings(findings: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for finding in findings:
        key = (
            finding.get("rule_id", ""),
            finding.get("source_path", ""),
            finding.get("section_key", ""),
            finding.get("subject_key", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _missing_entrypoint_findings() -> tuple[dict[str, str], ...]:
    return (
        _finding(
            rule_id="docs_entrypoint_present",
            source_path="repository-docs",
            section_key="repository-docs",
            subject_key="entrypoint-docs",
        ),
        _finding(
            rule_id="docs_setup_command_present",
            source_path="repository-docs",
            section_key="setup",
            subject_key="setup-command",
        ),
        _finding(
            rule_id="docs_qa_command_present",
            source_path="repository-docs",
            section_key="testing",
            subject_key="qa-command",
        ),
    )


def _first_source_name(source_paths: tuple[str, ...]) -> str:
    if not source_paths:
        return "repository-docs"
    first = source_paths[0].split(",", maxsplit=1)[0].strip()
    return _normalize_path_key(Path(first).name if first else "repository-docs")


def _detect_subject_key(section_text: str) -> str:
    lowered = section_text.lower()
    aliases = (
        (("gtk3 runtime", "gtk3", "gtk runtime", "libgobject-2.0-0"), "gtk3-runtime"),
        (("weasyprint",), "weasyprint"),
        (("poetry",), "poetry"),
        (("uv sync", "uv run", "`uv`", " uv "), "uv"),
        (("pytest",), "pytest"),
        (("venv", ".venv", "python"), "python-environment"),
        (("path", "dll"), "environment-mutation"),
    )
    for candidates, subject_key in aliases:
        if any(candidate in lowered for candidate in candidates):
            return subject_key
    first_line = section_text.splitlines()[0] if section_text.splitlines() else "docs-subject"
    return _normalize_subject_key(first_line)
