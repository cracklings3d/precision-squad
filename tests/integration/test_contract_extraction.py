"""Integration tests: real DocsFirstExecutor against fixture and programmatic repos.

These tests exercise the contract extraction pipeline without any GitHub
interaction. They validate that the executor correctly reads real README
files and produces the expected machine-readable artifacts.

These are the first vertical slice: they confirm that fixture repos are
well-formed before the pipeline tests use them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad.executor import DocsFirstExecutor
from precision_squad.models import (
    ExecutionResult,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RunRecord,
)


def _intake() -> IssueIntake:
    return IssueIntake(
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


def _record(run_dir: Path) -> RunRecord:
    return RunRecord(
        run_id="run-e2e-001",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-30T00:00:00Z",
        updated_at="2026-04-30T00:00:00Z",
        run_dir=str(run_dir),
    )


# ---------------------------------------------------------------------------
# Fixture-repo tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_clean_repo_extracts_full_contract(
    make_clean_repo,
    tmp_path: Path,
) -> None:
    """The clean-python fixture has clear docs; executor completes with no violations."""
    repo_path = make_clean_repo
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "completed"
    assert result.executor_name == "docs"
    assert "docs_contract_ready" in result.detail_codes

    contract_path = run_dir / "execution-contract" / "contract.json"
    assert contract_path.exists(), "contract.json should be written"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    assert any("pip" in cmd for cmd in contract["setup_commands"]), (
        f"setup_commands should contain a pip-based install: {contract['setup_commands']}"
    )
    assert contract["qa_command"] is not None, "qa_command should be extracted"
    assert "pytest" in contract["qa_command"].lower(), f"qa_command should be pytest: {contract['qa_command']}"
    assert contract["violations"] == [], f"no violations expected for clean repo: {contract['violations']}"
    assert contract["findings"] == [], f"no findings expected for clean repo: {contract['findings']}"


@pytest.mark.integration
def test_clean_repo_persists_all_artifacts(
    make_clean_repo,
    tmp_path: Path,
) -> None:
    """Execution contract directory contains contract.json and README.snapshot.md.

    docs-fix-prompt.txt is only written when there are policy violations,
    so it is absent for a clean repo.
    """
    repo_path = make_clean_repo
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    contract_dir = run_dir / "execution-contract"
    assert (contract_dir / "contract.json").exists(), "contract.json missing"
    assert (contract_dir / "README.snapshot.md").exists(), "README.snapshot.md missing"
    assert not (contract_dir / "docs-fix-prompt.txt").exists(), (
        "docs-fix-prompt.txt should not exist for a clean repo"
    )


@pytest.mark.integration
@pytest.mark.parametrize("fixture_repo", ["markdown-pdf-renderer"], indirect=True)
def test_mdfr_repo_blocks_on_gtk3_prerequisite(
    fixture_repo,
    tmp_path: Path,
) -> None:
    """markdown-pdf-renderer fixture has GTK3 docs blockers; executor reports missing_docs."""
    repo_path = fixture_repo
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "missing_docs", (
        f"Expected missing_docs (GTK3 ambiguity), got {result.status}: {result.summary}"
    )
    assert "docs_setup_prerequisites_ambiguous" in result.detail_codes, (
        f"Expected docs_setup_prerequisites_ambiguous, got {result.detail_codes}"
    )
    assert "gtk3" in result.summary.lower() or any(
        "gtk3" in str(d).lower() for d in result.detail_codes
    ), f"Summary should reference GTK3: {result.summary}"

    contract_path = run_dir / "execution-contract" / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert "docs_setup_prerequisite_manual_only" in contract["violations"], (
        f"Expected manual_only violation, got {contract['violations']}"
    )


@pytest.mark.integration
@pytest.mark.parametrize("fixture_repo", ["markdown-pdf-renderer"], indirect=True)
def test_mdfr_contract_contains_gtk3_findings(
    fixture_repo,
    tmp_path: Path,
) -> None:
    """The markdown-pdf-renderer contract findings should reference gtk3-runtime."""
    repo_path = fixture_repo
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    contract_path = run_dir / "execution-contract" / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    findings = contract.get("findings", [])

    gtk_findings = [
        f for f in findings
        if "gtk3" in f.get("subject_key", "").lower()
    ]
    assert gtk_findings, f"Expected GTK-related findings, got: {findings}"


# ---------------------------------------------------------------------------
# Programmatic repo tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_empty_repo_reports_missing_docs(
    make_empty_repo,
    tmp_path: Path,
) -> None:
    """A repo with no README triggers missing_docs."""
    repo_path = make_empty_repo
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "missing_docs"
    assert "docs_missing" in result.detail_codes


@pytest.mark.integration
def test_conflicting_docs_reports_ambiguous(
    make_ambiguous_repo,
    tmp_path: Path,
) -> None:
    """A repo where README and CONTRIBUTING give different setup commands is ambiguous."""
    repo_path = make_ambiguous_repo
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_path).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "ambiguous_docs", (
        f"Expected ambiguous_docs, got {result.status}: {result.summary}"
    )
    assert "docs_ambiguous" in result.detail_codes

    contract_path = run_dir / "execution-contract" / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert "docs_setup_command_unambiguous" in contract["violations"], (
        f"Expected ambiguous setup violation, got {contract['violations']}"
    )


@pytest.mark.integration
def test_readme_without_install_triggers_missing_setup(
    tmp_path: Path,
) -> None:
    """A README with a QA command but no installation section blocks on missing setup."""
    repo_root = tmp_path / "no-install-repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# Test\n\n## Testing\n```bash\npython -m pytest\n```\n",
        encoding="utf-8",
    )
    _init_simple_git_repo(repo_root)

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_root).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "missing_docs"
    assert "docs_setup_command_missing" in result.detail_codes


@pytest.mark.integration
def test_readme_without_qa_triggers_missing_qa(
    tmp_path: Path,
) -> None:
    """A README with an install section but no QA command blocks on missing QA."""
    repo_root = tmp_path / "no-qa-repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# Test\n\n## Installation\n```bash\npython -m pip install -e .\n```\n",
        encoding="utf-8",
    )
    _init_simple_git_repo(repo_root)

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = DocsFirstExecutor(repo_path=repo_root).execute(_intake(), _record(run_dir), run_dir)

    assert result.status == "missing_docs"
    assert "docs_qa_command_missing" in result.detail_codes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_simple_git_repo(repo_root: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo_root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_root, check=True, capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_root, check=True, capture_output=True,
    )
