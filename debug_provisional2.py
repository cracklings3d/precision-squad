"""Debug script - runs the full RunCoordinator flow for provisional."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    GitHubIssue,
    IssueAssessment,
    IssueReference,
    IssueIntake,
)
from tests.integration.test_pipeline_provisional import (
    _ProvisionalTestDependencies,
    _runnable_intake,
)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Create the failing repo (same as make_repo_with_failing_tests)
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

        subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=repo_root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True)
        print(f"Created failing repo at {repo_root}")

        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        params = RepairIssueParams(
            issue_ref="cracklings3d/markdown-pdf-renderer#9",
            runs_dir=runs_dir,
            repo_path=repo_root,
            publish=False,
            repair_agent="opencode",
            repair_model=None,
            review_model=None,
        )

        deps = _ProvisionalTestDependencies()

        print("\n=== Running RunCoordinator.repair_issue() ===")
        report = RunCoordinator().repair_issue(
            params=params,
            intake=_runnable_intake(),
            dependencies=deps,
        )

        print(f"\nResult:")
        print(f"  governance_verdict.status: {report.governance_verdict.status}")
        print(f"  baseline_qa_result.status: {report.baseline_qa_result.status if report.baseline_qa_result else None}")
        print(f"  baseline_qa_result.detail_codes: {report.baseline_qa_result.detail_codes if report.baseline_qa_result else None}")
        print(f"  qa_result.status: {report.qa_result.status if report.qa_result else None}")
        print(f"  qa_result.detail_codes: {report.qa_result.detail_codes if report.qa_result else None}")
        print(f"  execution_result.status: {report.execution_result.status if report.execution_result else None}")
        print(f"  execution_result.detail_codes: {report.execution_result.detail_codes if report.execution_result else None}")
        print(f"  exit_code: {report.exit_code}")
        print(f"  governance_verdict.summary: {report.governance_verdict.summary}")


if __name__ == "__main__":
    main()
