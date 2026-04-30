"""Debug why baseline QA passes instead of failing for the failing-test repo."""
import subprocess
import sys
import tempfile
import json
from pathlib import Path

sys.path.insert(0, "src")

from precision_squad.executor import DocsFirstExecutor
from precision_squad.models import (
    GitHubIssue,
    IssueAssessment,
    IssueReference,
    IssueIntake,
)
from precision_squad.repair.qa import _run_baseline_qa, WorkspaceQaVerifier


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Create the failing repo
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

        # Git init
        subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=repo_root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True)
        print(f"Created failing repo at {repo_root}")

        # Create a mock run record using the actual RunRecord constructor
        from precision_squad.models import RunRecord
        run_record = RunRecord(
            run_id="test-run",
            issue_ref="test/test#1",
            status="runnable",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            run_dir=str(runs_dir / "test-run"),
        )

        run_record_dir = runs_dir / "test-run"
        run_record_dir.mkdir(parents=True)
        run_dir = run_record_dir

        intake = IssueIntake(
            issue=GitHubIssue(
                reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
                title="Test",
                body="Test",
                labels=(),
                html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
            ),
            summary="Test",
            problem_statement="Test",
            assessment=IssueAssessment(status="runnable", reason_codes=()),
        )

        print("\n=== Running DocsFirstExecutor ===")
        synthesis_result = DocsFirstExecutor(repo_path=repo_root).execute(
            intake, run_record, run_dir
        )
        print(f"Synthesis status: {synthesis_result.status}")
        print(f"Synthesis detail codes: {synthesis_result.detail_codes}")

        contract_path = run_dir / "execution-contract" / "contract.json"
        if contract_path.exists():
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            print(f"\nContract qa_command: {contract.get('qa_command')}")
            print(f"Contract setup_commands: {contract.get('setup_commands')}")
            print(f"Contract violations: {contract.get('violations')}")
        else:
            print(f"\nContract not found at {contract_path}")
            # List files in run_dir
            for f in run_dir.rglob("*"):
                print(f"  Found: {f}")

        # Now run baseline QA
        print("\n=== Running baseline QA ===")
        verifier = WorkspaceQaVerifier()
        baseline_result = _run_baseline_qa(
            repo_path=repo_root,
            run_dir=run_dir,
            contract_artifact_dir=run_dir / "execution-contract",
            verifier=verifier,
        )
        print(f"Baseline QA status: {baseline_result.status}")
        print(f"Baseline QA detail codes: {baseline_result.detail_codes}")
        print(f"Baseline QA summary: {baseline_result.summary}")
        if baseline_result.stdout_path:
            stdout = Path(baseline_result.stdout_path).read_text(encoding="utf-8", errors="ignore")
            print(f"Baseline QA stdout:\n{stdout}")
        if baseline_result.stderr_path:
            stderr = Path(baseline_result.stderr_path).read_text(encoding="utf-8", errors="ignore")
            print(f"Baseline QA stderr:\n{stderr}")


if __name__ == "__main__":
    main()
