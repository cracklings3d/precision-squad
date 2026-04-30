"""Shared fixtures and helpers for precision-squad integration tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from precision_squad.models import (
    ExecutionResult,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    RepairResult,
    RunRecord,
)


# ---------------------------------------------------------------------------
# GitHub token
# ---------------------------------------------------------------------------


@pytest.fixture
def github_token() -> str:
    """Return the GITHUB_TOKEN from the environment, or skip if not set."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        pytest.skip("GITHUB_TOKEN is not set")
    return token


# ---------------------------------------------------------------------------
# Fixture repository helpers
# ---------------------------------------------------------------------------

_FIXTURE_REPOS_ROOT = Path(__file__).parent.parent / ".test-repos"


@pytest.fixture
def fixture_repo(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """Return a fresh copy of a named fixture repository in tmp_path.

    Usage (requires indirect parametrization):
        @pytest.mark.parametrize("fixture_repo", ["markdown-pdf-renderer"], indirect=True)
        def test_something(fixture_repo: Path):
            ...

    The fixture repo name must match a subdirectory under
    tests/.test-repos/<name>/.
    """
    name = request.param  # type: ignore[attr-defined]
    source = _FIXTURE_REPOS_ROOT / name
    if not source.exists():
        pytest.skip(f"Fixture repository '{name}' not found at {source}")
    dest = tmp_path / name
    shutil.copytree(source, dest, symlinks=True)
    return dest


@pytest.fixture
def make_clean_repo(tmp_path: Path) -> Path:
    """Create a minimal git repository with clean docs and passing tests.

    The repo has:
    - A README.md with ## Installation and ## Testing sections
    - A pyproject.toml with pytest in dev dependencies
    - A trivial src/ package with one function
    - A test that passes
    - One git commit

    Returns the path to the repository root.
    """
    repo_root = tmp_path / "clean-repo"
    repo_root.mkdir()

    src_pkg = repo_root / "src" / "clean_pkg"
    src_pkg.mkdir(parents=True)

    tests_dir = repo_root / "tests"
    tests_dir.mkdir()

    (src_pkg / "__init__.py").write_text('"""Package."""\n', encoding="utf-8")
    (src_pkg / "core.py").write_text('"""Core."""\n\ndef greet(name: str) -> str:\n    return f"Hello, {name}!"\n', encoding="utf-8")
    (tests_dir / "test_core.py").write_text(
        '"""Tests."""\nfrom clean_pkg.core import greet\n\ndef test_greet():\n    assert greet("world") == "Hello, world!"\n',
        encoding="utf-8",
    )
    (repo_root / "README.md").write_text(
        "# Clean Repo\n\n## Installation\n```bash\npython -m pip install -e .[dev]\n```\n\n## Testing\n```bash\npython -m pytest\n```\n",
        encoding="utf-8",
    )
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname = 'clean-pkg'\nversion = '0.1.0'\nrequires-python = '>=3.10'\ndependencies = []\n\n[project.optional-dependencies]\ndev = ['pytest>=8.0']\n\n[tool.setuptools.packages.find]\nwhere = ['src']\n",
        encoding="utf-8",
    )
    _init_git_repo(repo_root)
    return repo_root


@pytest.fixture
def make_empty_repo(tmp_path: Path) -> Path:
    """Create a git repository with no README (triggers docs_missing).

    Creates a pyproject.toml so git can commit, but deliberately omits any
    README or CONTRIBUTING file to trigger the docs_missing blocker.
    """
    repo_root = tmp_path / "empty-repo"
    repo_root.mkdir()

    (repo_root / "pyproject.toml").write_text(
        "[project]\nname = 'empty'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    _init_git_repo(repo_root)
    return repo_root


@pytest.fixture
def make_ambiguous_repo(tmp_path: Path) -> Path:
    """Create a git repository with conflicting setup instructions.

    README.md says "pip install" but CONTRIBUTING.md says "uv sync".
    This should trigger ambiguous_docs status.
    """
    repo_root = tmp_path / "ambiguous-repo"
    repo_root.mkdir()

    src_pkg = repo_root / "src" / "amb_pkg"
    src_pkg.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text('"""Package."""\n', encoding="utf-8")

    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_core.py").write_text(
        '"""Tests."""\ndef test_ok():\n    assert True\n',
        encoding="utf-8",
    )

    (repo_root / "README.md").write_text(
        "# Project\n\n## Installation\n```bash\npip install -e .[dev]\n```\n\n## Testing\n```bash\npytest\n```\n",
        encoding="utf-8",
    )
    (repo_root / "CONTRIBUTING.md").write_text(
        "# Contributing\n\n## Setup\n```bash\nuv sync\n```\n\n## Testing\n```bash\npytest\n```\n",
        encoding="utf-8",
    )
    _init_git_repo(repo_root)
    return repo_root


@pytest.fixture
def make_repo_with_failing_tests(tmp_path: Path) -> Path:
    """Create a git repository with one passing and one failing test.

    This is used to test the baseline-tolerance (provisional) path:
    baseline QA fails, repair improves (failing test is removed), final QA
    passes, governance marks as provisional.
    """
    repo_root = tmp_path / "failing-repo"
    repo_root.mkdir()

    src_pkg = repo_root / "src" / "fail_pkg"
    src_pkg.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text('"""Package."""\n', encoding="utf-8")
    (src_pkg / "core.py").write_text(
        '"""Core."""\n\ndef greet(name: str) -> str:\n    return f"Hello, {name}!"\n\ndef fail() -> None:\n    raise RuntimeError("intentional failure")\n',
        encoding="utf-8",
    )

    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_core.py").write_text(
        '"""Tests."""\nfrom fail_pkg.core import greet, fail\n\ndef test_greet():\n    assert greet("world") == "Hello, world!"\n\ndef test_fail():\n    fail()  # This test fails intentionally\n',
        encoding="utf-8",
    )

    (repo_root / "README.md").write_text(
        "# Failing Repo\n\n## Installation\n```bash\npython -m pip install -e .[dev]\n```\n\n## Testing\n```bash\npython -m pytest\n```\n",
        encoding="utf-8",
    )
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname = 'fail-pkg'\nversion = '0.1.0'\nrequires-python = '>=3.10'\ndependencies = []\n\n[project.optional-dependencies]\ndev = ['pytest>=8.0']\n\n[tool.setuptools.packages.find]\nwhere = ['src']\n",
        encoding="utf-8",
    )
    _init_git_repo(repo_root)
    return repo_root


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo_root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=repo_root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_root, check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Stub repair adapters
# ---------------------------------------------------------------------------


class StubRepairAdapter:
    """A trivial repair adapter that makes a predictable file change.

    This replaces OpenCodeRepairAdapter in integration tests where we want
    to exercise the full pipeline without running a real opencode model.
    """

    def __init__(
        self,
        file_content: str = "# precision-squad: repaired\n",
    ) -> None:
        self.binary: str | None = None
        self.agent: str | None = None
        self.model: str | None = None
        self.qa_feedback: str | None = None
        self._file_content = file_content

    def repair(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
    ) -> RepairResult:
        repo_workspace.resolve()

        init_file = self._find_init(repo_workspace)
        if init_file and init_file.exists():
            init_file.write_text(
                init_file.read_text(encoding="utf-8") + self._file_content,
                encoding="utf-8",
            )

        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "repair: applied stub fix"],
            cwd=repo_workspace,
            check=True,
            capture_output=True,
        )

        patch_proc = subprocess.run(
            ["git", "diff", "--binary", "HEAD~1", "HEAD"],
            cwd=repo_workspace,
            capture_output=True,
            text=True,
        )
        patch_path = run_dir / "repair.patch"
        patch_path.write_text(patch_proc.stdout or "", encoding="utf-8")

        return RepairResult(
            status="completed",
            summary="Stub repair completed and produced source changes.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repo_workspace.parent),
            patch_path=str(patch_path),
        )

    def _find_init(self, repo_workspace: Path) -> Path | None:
        candidates = [
            repo_workspace / "src" / "__init__.py",
            repo_workspace / "__init__.py",
        ]
        for src_dir in (repo_workspace / "src").iterdir():
            if src_dir.is_dir() and (src_dir / "__init__.py").exists():
                return src_dir / "__init__.py"
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None


@pytest.fixture
def stub_repair_adapter() -> StubRepairAdapter:
    """Return a stub repair adapter that appends a comment to __init__.py."""
    return StubRepairAdapter()


def make_tailored_repair_adapter(
    content: str = "# precision-squad: repaired\n",
) -> StubRepairAdapter:
    """Return a stub adapter that writes a specific string to a package __init__.py."""
    return StubRepairAdapter(file_content=content)


# ---------------------------------------------------------------------------
# Issue intake helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def runnable_intake() -> IssueIntake:
    """Return a standard runnable IssueIntake for owner/repo#9."""
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


@pytest.fixture
def plan_issue_intake() -> IssueIntake:
    """Return a blocked IssueIntake for a plan-labeled issue."""
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 1),
            title="[Plan] Markdown to PDF Renderer",
            body="## Project Plan\nThis is the plan.",
            labels=("plan",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/1",
        ),
        summary="Markdown to PDF Renderer",
        problem_statement="Project plan",
        assessment=IssueAssessment(
            status="blocked",
            reason_codes=("issue_marked_as_plan",),
        ),
    )


@pytest.fixture
def docs_remediation_intake() -> IssueIntake:
    """Return a runnable IssueIntake for a docs-remediation issue."""
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body=(
                "<!-- precision-squad:docs-remediation -->\n"
                "<!-- precision-squad:target-findings:[{\"rule_id\":\"docs_setup_prerequisites_ambiguous\",\"section_key\":\"docs\",\"source_path\":\"repository-docs\",\"subject_key\":\"docs-blocker\"}] -->\n\n"
                "## Context\nFix docs."
            ),
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )


# ---------------------------------------------------------------------------
# Real GitHub clients (require token -- use github_token fixture first)
# ---------------------------------------------------------------------------


@pytest.fixture
def real_github_issue_client(github_token: str):
    """Return a real GitHubIssueClient for the configured token."""
    from precision_squad.github_client import GitHubIssueClient

    return GitHubIssueClient(token=github_token)


@pytest.fixture
def real_github_write_client(github_token: str):
    """Return a real GitHubWriteClient for the configured token."""
    from precision_squad.github_client import GitHubWriteClient

    return GitHubWriteClient(token=github_token)
