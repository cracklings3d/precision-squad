"""Integration tests: docs-remediation pipeline path.

Exercises the full docs-remediation flow:
1. Docs-remediation issue detected via issue body markers
2. Repair adapter fixes the README with correct GTK3 instructions
3. Re-validation extractor runs on the repaired workspace
4. Governance verdict based on revalidation result
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import IssueIntake

# ---------------------------------------------------------------------------
# Tailored repair adapters for docs-remediation scenarios
# ---------------------------------------------------------------------------

class _DocsFixRepairAdapter:
    """Repair adapter that fixes the GTK3 section in README.md.

    The markdown-pdf-renderer fixture README mentions downloading GTK3 from a
    URL without an exact version or a post-install verification command.
    This adapter rewrites that section with explicit instructions.
    """

    def __init__(self) -> None:
        self.binary: str | None = None
        self.agent: str | None = None
        self.model: str | None = None
        self.qa_feedback: str | None = None

    def repair(
        self,
        *,
        intake: IssueIntake,
        run_record,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
    ):
        import subprocess

        readme = repo_workspace / "README.md"
        if readme.exists():
            original = readme.read_text(encoding="utf-8")
            fixed = original.replace(
                "## Windows System Dependencies\n\n"
                "WeasyPrint requires GTK3 runtime libraries on Windows. "
                "If you encounter errors like `cannot load library "
                "'libgobject-2.0-0'`, install the GTK3 runtime:\n\n"
                "1. Download GTK3 from "
                "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer\n"
                "2. Run the installer\n"
                "3. Restart your terminal and run `python -m pip install -e \".[dev]\"` again",
                "## Windows System Dependencies\n\n"
                "WeasyPrint requires GTK3 runtime libraries on Windows. "
                "Install the official release via winget:\n\n"
                "```powershell\n"
                "winget install Gtk3.Runtime --accept-source-agreements --accept-package-agreements\n"
                "```\n\n"
                "Verify GTK3 is available:\n"
                "```powershell\n"
                "python -c \"import ctypes; ctypes.CDLL('libgobject-2.0-0')\"\n"
                "```\n\n"
                "**Environment assumptions**: GTK3 DLLs must be on the system PATH. "
                "Open a new PowerShell session after installation so the active shell "
                "sees the updated PATH.\n",
            )
            readme.write_text(fixed, encoding="utf-8")

        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "repair: fix GTK3 documentation with exact commands"],
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

        from precision_squad.models import RepairResult

        return RepairResult(
            status="completed",
            summary="Docs-remediation repair: fixed GTK3 section in README.md.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repo_workspace.parent),
            patch_path=str(patch_path),
        )


class _NoOpRepairAdapter:
    """Repair adapter that makes no changes (simulates a repair that didn't fix docs)."""

    def __init__(self) -> None:
        self.binary: str | None = None
        self.agent: str | None = None
        self.model: str | None = None
        self.qa_feedback: str | None = None

    def repair(self, **kwargs):
        import subprocess

        from precision_squad.models import RepairResult

        kwargs = kwargs
        subprocess.run(["git", "add", "-A"], capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "noop repair"],
            capture_output=True,
        )
        return RepairResult(
            status="completed",
            summary="Repair stage ran but made no changes.",
            detail_codes=("repair_produced_no_changes",),
            workspace_path=str(kwargs["repo_workspace"].parent),
            patch_path="",
        )


# ---------------------------------------------------------------------------
# Test dependencies wiring for docs-remediation path
# ---------------------------------------------------------------------------

class _DocsRemediationDependencies:
    """Wires the docs-remediation repair path through RunCoordinator."""

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    def create_repair_adapter(self, *, repair_agent: str, repair_model: str | None):
        if repair_agent == "none":
            return None
        return self._adapter

    def run_repair_qa_loop(self, **kwargs):
        raise AssertionError("normal repair loop should not run for docs-remediation issue")

    def run_docs_remediation_repair(self, **kwargs):
        from precision_squad.repair.orchestration import run_docs_remediation_repair as _real

        return _real(**kwargs)

    def evaluate_docs_remediation_validation(self, **kwargs):
        from precision_squad.repair.orchestration import (
            evaluate_docs_remediation_validation as _real,
        )

        return _real(**kwargs)

    def merge_docs_remediation_execution_result(
        self,
        synthesis_result,
        repair_result,
        validation_result,
        validation_scope_summary=None,
    ):
        from precision_squad.repair.orchestration import (
            merge_docs_remediation_execution_result as _real,
        )

        return _real(
            synthesis_result,
            repair_result,
            validation_result,
            validation_scope_summary,
        )

    def merge_execution_result(self, synthesis_result, repair_result, qa_result=None):
        from precision_squad.repair.orchestration import merge_execution_result as _real

        return _real(synthesis_result, repair_result, qa_result)

    def synthesis_artifacts_ready(self, execution_result):
        from precision_squad.repair.orchestration import synthesis_artifacts_ready as _real

        return _real(execution_result)

    def execute_publish_plan(self, intake, plan, *, publish, run_dir=None):
        from precision_squad.models import PublishResult

        return PublishResult(
            status="dry_run",
            target=plan.status,
            summary="dry_run (integration test)",
            url=None,
        )

    def run_post_publish_review_if_needed(self, **kwargs):
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("fixture_repo", ["markdown-pdf-renderer"], indirect=True)
def test_docs_remediation_succeeds_after_fix(
    fixture_repo,
    tmp_path: Path,
) -> None:
    """Docs-remediation repair fixes README; revalidation passes; governance approved."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    repo_path = fixture_repo  # a fresh copy of markdown-pdf-renderer

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#16",
        runs_dir=runs_dir,
        repo_path=repo_path,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
    )

    deps = _DocsRemediationDependencies(_DocsFixRepairAdapter())

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_docs_remediation_intake(),
        dependencies=deps,
    )

    assert report.execution_result is not None
    assert report.execution_result.status == "completed", (
        f"Expected completed, got {report.execution_result.status}: "
        f"{report.execution_result.summary}"
    )
    assert "docs_remediation_issue" in report.execution_result.detail_codes
    assert report.governance_verdict.status == "approved", (
        f"Expected approved, got {report.governance_verdict.status}: "
        f"{report.governance_verdict.summary}"
    )
    assert report.publish_plan.status == "draft_pr"
    assert report.exit_code == 0


@pytest.mark.integration
@pytest.mark.parametrize("fixture_repo", ["markdown-pdf-renderer"], indirect=True)
def test_docs_remediation_stays_blocked_without_fix(
    fixture_repo,
    tmp_path: Path,
) -> None:
    """No-op repair; revalidation still finds GTK3 blockers; governance blocked."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    repo_path = fixture_repo

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#16",
        runs_dir=runs_dir,
        repo_path=repo_path,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
    )

    deps = _DocsRemediationDependencies(_NoOpRepairAdapter())

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_docs_remediation_intake(),
        dependencies=deps,
    )

    assert report.execution_result is not None
    assert report.execution_result.status in {"missing_docs", "blocked"}, (
        f"Expected missing_docs or blocked, got {report.execution_result.status}: "
        f"{report.execution_result.summary}"
    )
    assert report.governance_verdict.status == "blocked", (
        f"Expected blocked, got {report.governance_verdict.status}: "
        f"{report.governance_verdict.summary}"
    )
    assert report.publish_plan.status in {"issue_comment", "follow_up_issue"}


@pytest.mark.integration
@pytest.mark.parametrize("fixture_repo", ["markdown-pdf-renderer"], indirect=True)
def test_docs_remediation_persists_repair_artifacts(
    fixture_repo,
    tmp_path: Path,
) -> None:
    """Docs-remediation run persists repair-result.json and validation artifacts."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    repo_path = fixture_repo

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#16",
        runs_dir=runs_dir,
        repo_path=repo_path,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
    )

    deps = _DocsRemediationDependencies(_DocsFixRepairAdapter())

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_docs_remediation_intake(),
        dependencies=deps,
    )

    run_dir = Path(report.run_record.run_dir)
    assert (run_dir / "repair-result.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert (run_dir / "publish-plan.json").exists()

    repair_result = json.loads(
        (run_dir / "repair-result.json").read_text(encoding="utf-8")
    )
    assert repair_result["status"] == "completed"


def _docs_remediation_intake() -> IssueIntake:
    from precision_squad.models import GitHubIssue, IssueAssessment, IssueReference

    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body=(
                "<!-- precision-squad:docs-remediation -->\n"
                "<!-- precision-squad:target-findings:["
                "{\"rule_id\":\"docs_setup_prerequisites_ambiguous\","
                "\"section_key\":\"windows-system-dependencies\","
                "\"source_path\":\"readme.md\","
                "\"subject_key\":\"gtk3-runtime\"}"
                "] -->\n\n"
                "## Context\nFix docs."
            ),
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )
