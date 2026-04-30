"""Debug script for provisional test - better error reporting."""
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

        repo_root = tmp_path / "failing-repo"
        repo_root.mkdir()
        src_pkg = repo_root / "src" / "fail_pkg"
        src_pkg.mkdir(parents=True)
        (src_pkg / "__init__.py").write_text('"""Package."""\n', encoding="utf-8")
        (src_pkg / "core.py").write_text(
            '"""Core."""\n\ndef greet(name): return f"Hello, {name}!"\ndef fail(): raise RuntimeError("intentional failure")\n',
            encoding="utf-8",
        )
        tests_dir = repo_root / "tests"
        tests_dir.mkdir()
        test_content = (
            "from fail_pkg.core import greet, fail\n\n"
            "def test_greet():\n"
            "    assert greet('world') == 'Hello, world!'\n\n"
            "def test_fail():\n"
            "    fail()\n"
        )
        (tests_dir / "test_core.py").write_text(test_content, encoding="utf-8")
        print(f"Test file content:\n{(tests_dir / 'test_core.py').read_text(encoding='utf-8')!r}")

        (repo_root / "README.md").write_text(
            "# Failing Repo\n\n"
            "## Installation\n"
            "python -m pip install -e .[dev]\n\n"
            "## Testing\n"
            "python -m pytest\n",
            encoding="utf-8",
        )
        (repo_root / "pyproject.toml").write_text(
            "[project]\n"
            "name = 'fail-pkg'\n"
            "version = '0.1.0'\n"
            "requires-python = '>=3.10'\n"
            "dependencies = []\n\n"
            "[project.optional-dependencies]\n"
            "dev = ['pytest>=8.0']\n\n"
            "[tool.setuptools.packages.find]\n"
            "where = ['src']\n",
            encoding="utf-8",
        )

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
        print("Initial commit done")

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

        # Test git operations directly
        from tests.integration.test_pipeline_provisional import (
            _RepairAdapterThatFixesFailingTest,
        )

        adapter = _RepairAdapterThatFixesFailingTest()
        repo_workspace = tmp_path / "test-workspace" / "repo"
        repo_workspace.mkdir(parents=True)
        subprocess.run(
            ["git", "clone", str(repo_root), str(repo_workspace)],
            cwd=tmp_path / "test-workspace",
            capture_output=True,
            text=True,
        )
        print(f"Cloned repo to {repo_workspace}")

        # Test the repair
        import os
        env = os.environ.copy()
        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_workspace,
            capture_output=True,
            text=True,
        )
        print(f"git add result: returncode={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}")

        result = subprocess.run(
            ["git", "commit", "-m", "repair test"],
            cwd=repo_workspace,
            capture_output=True,
            text=True,
        )
        print(f"git commit result: returncode={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}")

        # Now test the adapter
        test_file = repo_workspace / "tests" / "test_core.py"
        print(f"Test file exists: {test_file.exists()}")
        original = test_file.read_text(encoding="utf-8")
        print(f"Original content:\n{original!r}")
        search_for = "\ndef test_fail():\n    fail()  # This test fails intentionally\n"
        print(f"Search for: {search_for!r}")
        print(f"Found: {search_for in original}")

        fixed = original.replace(search_for, "")
        print(f"Fixed content:\n{fixed!r}")
        test_file.write_text(fixed, encoding="utf-8")

        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_workspace,
            capture_output=True,
            text=True,
        )
        print(f"After fix - git add result: returncode={result.returncode}")

        result = subprocess.run(
            ["git", "commit", "-m", "repair: remove failing test"],
            cwd=repo_workspace,
            capture_output=True,
            text=True,
        )
        print(f"After fix - git commit result: returncode={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}")


if __name__ == "__main__":
    main()
