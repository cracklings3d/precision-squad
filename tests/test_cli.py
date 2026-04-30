"""Tests for the bootstrap CLI surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad import __version__
from precision_squad.bootstrap import main as bootstrap_main
from precision_squad.cli import main
from precision_squad.models import (
    ExecutionResult,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    PostPublishReviewResult,
)


def test_main_without_args_shows_help(capsys) -> None:
    status = main([])

    captured = capsys.readouterr()
    assert status == 0
    assert "precision-squad" in captured.out
    assert "run" in captured.out


def test_version_flag_shows_package_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert __version__ in captured.out


def test_install_skill_writes_skill_md(capsys, tmp_path: Path) -> None:
    status = main(["install-skill", "--project-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert (tmp_path / "SKILL.md").exists()
    assert "Installed skill:" in captured.out


def test_install_skill_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("existing\n", encoding="utf-8")

    status = main(["install-skill", "--project-root", str(tmp_path)])

    assert status == 1
    assert skill_path.read_text(encoding="utf-8") == "existing\n"


def test_bootstrap_skill_cancels_without_confirmation(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    status = bootstrap_main(["--project-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert "Bootstrap cancelled" in captured.out
    assert not (tmp_path / "SKILL.md").exists()


def test_bootstrap_skill_installs_after_confirmation(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")

    status = bootstrap_main(["--project-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert "This bootstrap will install the precision-squad project skill." in captured.out
    assert (tmp_path / "SKILL.md").exists()


def test_run_issue_placeholder_returns_nonzero(
    capsys, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OpenCode_Github_Token", raising=False)

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "github token" in captured.err.lower()


def test_run_issue_prints_runnable_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Stub execution completed.",
            detail_codes=(),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Classification: runnable" in captured.out
    assert "Run ID:" in captured.out
    assert "Summary: Add --version flag to CLI" in captured.out
    assert "Execution Status: completed" in captured.out


def test_repair_issue_alias_prints_runnable_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Stub execution completed.",
            detail_codes=(),
        ),
    )

    status = main(
        [
            "repair",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Classification: runnable" in captured.out
    assert "Execution Status: completed" in captured.out


def test_run_issue_prints_blocked_intake(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 1),
            title="[Plan] Markdown to PDF Renderer",
            body="## Project Plan",
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#1",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 3
    assert "Classification: blocked" in captured.out
    assert "issue_marked_as_plan" in captured.out
    assert "Governance: blocked" in captured.out
    assert "Publish Plan: issue_comment" in captured.out
    assert "Publish Result: dry_run" in captured.out


def test_run_issue_persists_run_artifacts(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Stub execution completed.",
            detail_codes=(),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    run_dir_line = next(line for line in captured.out.splitlines() if line.startswith("Run Dir:"))
    run_dir = Path(run_dir_line.removeprefix("Run Dir:").strip())

    assert status == 0
    assert (run_dir / "run-request.json").exists()
    assert (run_dir / "issue-intake.json").exists()
    assert (run_dir / "run-record.json").exists()
    assert (run_dir / "execution-result.json").exists()
    assert (run_dir / "evaluation-result.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert (run_dir / "publish-plan.json").exists()
    assert (run_dir / "publish-result.json").exists()


def test_run_issue_uses_executor_and_persists_execution_result(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="blocked",
            executor_name="docs",
            summary="Executor wiring is not implemented yet.",
            detail_codes=("executor_not_implemented",),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    run_dir_line = next(line for line in captured.out.splitlines() if line.startswith("Run Dir:"))
    run_dir = Path(run_dir_line.removeprefix("Run Dir:").strip())

    assert status == 4
    assert (run_dir / "execution-result.json").exists()
    assert (run_dir / "evaluation-result.json").exists()
    assert (run_dir / "governance-verdict.json").exists()
    assert (run_dir / "publish-plan.json").exists()
    assert (run_dir / "publish-result.json").exists()
    assert "Execution Status: blocked" in captured.out
    assert "Publish Plan: issue_comment" in captured.out
    assert "Publish Result: dry_run" in captured.out


def test_run_issue_does_not_enter_repair_loop_when_docs_are_missing(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)
    monkeypatch.setattr(
        "precision_squad.cli.DocsFirstExecutor.execute",
        lambda self, intake, record, run_dir: ExecutionResult(
            status="missing_docs",
            executor_name="docs",
            summary="Missing documented QA command.",
            detail_codes=("docs_qa_command_missing",),
            artifact_dir=str(run_dir / "execution-contract"),
        ),
    )

    def fail_if_repair_runs(**kwargs):
        raise AssertionError("repair loop should not run when docs are missing")

    monkeypatch.setattr("precision_squad.cli.run_repair_qa_loop", fail_if_repair_runs)

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 4
    assert "Execution Status: missing_docs" in captured.out
    assert "Governance: blocked" in captured.out
    assert "Publish Plan: follow_up_issue" in captured.out
    assert "Publish Result: dry_run" in captured.out


def test_docs_remediation_issue_runs_repair_without_recursive_follow_up_issue(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    workspace_root = tmp_path / "workspace"
    (workspace_root / "repo").mkdir(parents=True)

    def fake_execute(self, intake, record, run_dir):
        repo_path = self.repo_path
        del intake, record
        artifact_dir = run_dir / "execution-contract"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "contract.json").write_text("{}\n", encoding="utf-8")
        (artifact_dir / "docs-fix-prompt.txt").write_text("Fix docs.\n", encoding="utf-8")
        (artifact_dir / "README.snapshot.md").write_text("# README\n", encoding="utf-8")
        if repo_path == workspace_root / "repo":
            return ExecutionResult(
                status="completed",
                executor_name="docs",
                summary="Repository documentation yielded an explicit local setup and QA contract.",
                detail_codes=("docs_contract_ready",),
                artifact_dir=str(artifact_dir),
            )
        return ExecutionResult(
            status="missing_docs",
            executor_name="docs",
            summary="Missing documented QA command.",
            detail_codes=("docs_qa_command_missing",),
            artifact_dir=str(artifact_dir),
        )

    monkeypatch.setattr("precision_squad.cli.DocsFirstExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "precision_squad.cli.run_docs_remediation_repair",
        lambda **kwargs: __import__("precision_squad.models", fromlist=["RepairResult"]).RepairResult(
            status="completed",
            summary="Repair stage completed and produced source changes.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(workspace_root),
            patch_path=str(tmp_path / "repair.patch"),
        ),
    )

    def fail_if_standard_repair_runs(**kwargs):
        raise AssertionError("standard repair/QA loop should not run for docs-remediation issues")

    monkeypatch.setattr("precision_squad.cli.run_repair_qa_loop", fail_if_standard_repair_runs)

    status = main(
        [
            "repair",
            "issue",
            "cracklings3d/markdown-pdf-renderer#16",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Execution Status: completed" in captured.out
    assert "Repair Status: completed" in captured.out
    assert "Publish Plan: draft_pr" in captured.out


def test_docs_remediation_issue_stays_blocked_when_revalidation_fails(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 16),
            title="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
            body="<!-- precision-squad:docs-remediation -->\n\n## Context\nFix docs.",
            labels=(),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/16",
        ),
        summary="Docs blocker surfaced while repairing #9: clarify deterministic setup and QA",
        problem_statement="Fix docs.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    workspace_root = tmp_path / "workspace"
    (workspace_root / "repo").mkdir(parents=True)

    def fake_execute(self, intake, record, run_dir):
        del self, intake, record
        artifact_dir = run_dir / "execution-contract"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "contract.json").write_text(
            json.dumps(
                {
                    "findings": [
                        {
                            "rule_id": "docs_setup_prerequisites_ambiguous",
                            "source_path": "repository-docs",
                            "section_key": "docs",
                            "subject_key": "docs-blocker",
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (artifact_dir / "docs-fix-prompt.txt").write_text("Fix docs.\n", encoding="utf-8")
        (artifact_dir / "README.snapshot.md").write_text("# README\n", encoding="utf-8")
        return ExecutionResult(
            status="missing_docs",
            executor_name="docs",
            summary="Still missing deterministic setup guidance.",
            detail_codes=("docs_setup_prerequisites_ambiguous",),
            artifact_dir=str(artifact_dir),
        )

    monkeypatch.setattr("precision_squad.cli.DocsFirstExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "precision_squad.cli.run_docs_remediation_repair",
        lambda **kwargs: __import__("precision_squad.models", fromlist=["RepairResult"]).RepairResult(
            status="completed",
            summary="Repair stage completed and produced source changes.",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(workspace_root),
            patch_path=str(tmp_path / "repair.patch"),
        ),
    )
    monkeypatch.setattr(
        "precision_squad.cli.run_repair_qa_loop",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("standard repair/QA loop should not run for docs-remediation issues")
        ),
    )

    status = main(
        [
            "repair",
            "issue",
            "cracklings3d/markdown-pdf-renderer#16",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 4
    assert "Execution Status: missing_docs" in captured.out
    assert "Governance: blocked" in captured.out
    assert "Publish Plan: issue_comment" in captured.out


def test_run_issue_persists_repair_result_when_synthesis_artifacts_exist(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    def fake_execute(self, intake, record, run_dir):
        del self, intake
        artifact_dir = run_dir / "execution-contract"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "contract.json").write_text("{}\n", encoding="utf-8")
        return ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Documented execution contract ready.",
            detail_codes=("docs_contract_ready",),
            artifact_dir=str(artifact_dir),
        )

    monkeypatch.setattr("precision_squad.cli.DocsFirstExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "precision_squad.cli.run_repair_qa_loop",
        lambda **kwargs: (
            __import__("precision_squad.models", fromlist=["RepairResult"]).RepairResult(
                status="not_configured",
                summary=(
                    "A documented local execution contract was prepared, but no repair agent was configured."
                ),
                detail_codes=("repair_stage_not_configured",),
            ),
            __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
                status="failed",
                summary="Baseline QA failed.",
                detail_codes=("qa_failed",),
                phase="baseline",
            ),
            __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
                status="not_run",
                summary="QA did not run.",
                detail_codes=("qa_not_run",),
                phase="final",
            ),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--repair-agent",
            "none",
        ]
    )

    captured = capsys.readouterr()
    run_dir_line = next(line for line in captured.out.splitlines() if line.startswith("Run Dir:"))
    run_dir = Path(run_dir_line.removeprefix("Run Dir:").strip())

    assert status == 4
    assert (run_dir / "repair-result.json").exists()
    assert (run_dir / "qa-baseline-result.json").exists()
    assert (run_dir / "qa-result.json").exists()
    assert "Repair Status: not_configured" in captured.out
    assert "QA Status: not_run" in captured.out


def test_run_issue_marks_baseline_tolerant_success_approved(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intake = IssueIntake(
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

    monkeypatch.setattr("precision_squad.cli.load_issue_intake", lambda _: intake)

    def fake_execute(self, intake, record, run_dir):
        del self, intake
        artifact_dir = run_dir / "execution-contract"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "contract.json").write_text("{}\n", encoding="utf-8")
        return ExecutionResult(
            status="completed",
            executor_name="docs",
            summary="Documented execution contract ready.",
            detail_codes=("docs_contract_ready",),
            artifact_dir=str(artifact_dir),
        )

    monkeypatch.setattr("precision_squad.cli.DocsFirstExecutor.execute", fake_execute)
    monkeypatch.setattr(
        "precision_squad.cli.run_repair_qa_loop",
        lambda **kwargs: (
            __import__("precision_squad.models", fromlist=["RepairResult"]).RepairResult(
                status="completed",
                summary="Repair completed.",
                detail_codes=("repair_stage_completed",),
                workspace_path=str(tmp_path / "workspace"),
                patch_path=str(tmp_path / "repair.patch"),
            ),
            __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
                status="failed",
                summary="Baseline QA failed.",
                detail_codes=("qa_failed",),
                phase="baseline",
            ),
            __import__("precision_squad.models", fromlist=["QaResult"]).QaResult(
                status="failed",
                summary="Repair QA improved on baseline.",
                detail_codes=("qa_failed",),
                phase="final",
                quality="improved",
            ),
        ),
    )

    status = main(
        [
            "run",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(tmp_path / "repo"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Governance: approved" in captured.out
    assert "Publish Plan: draft_pr" in captured.out


def test_publish_run_reuses_existing_artifacts(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {
                        "owner": "cracklings3d",
                        "repo": "markdown-pdf-renderer",
                        "number": 9,
                    },
                    "title": "[Enhancement] Add --version flag to CLI",
                    "body": "## Description\nAdd a version flag.",
                    "labels": ["enhancement"],
                    "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
                    "comments": ["Prior rejection feedback"],
                },
                "summary": "Add --version flag to CLI",
                "problem_statement": "Add a version flag.",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-plan.json").write_text(
        json.dumps(
            {
                "status": "draft_pr",
                "title": "Add --version flag to CLI",
                "body": "body",
                "reason_codes": [],
                "pull_request_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/15",
                "pull_number": 15,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "status": "runnable",
                "created_at": "2026-04-27T00:00:00Z",
                "updated_at": "2026-04-27T00:00:00Z",
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-result.json").write_text(
        json.dumps(
            {
                "status": "dry_run",
                "target": "draft_pr",
                "summary": "dry run",
                "url": None,
                "branch_name": "precision-squad/run-20260428-012411-5e87af7f",
                "pull_number": 15,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "precision_squad.cli.execute_publish_plan",
        lambda intake, plan, publish, run_dir: __import__(
            "precision_squad.models", fromlist=["PublishResult"]
        ).PublishResult(
            status="published",
            target=plan.status,
            summary="Published existing run.",
            url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/15",
            branch_name="precision-squad/run-20260428-012411-5e87af7f",
            pull_number=15,
        ),
    )
    monkeypatch.setattr(
        "precision_squad.cli._run_post_publish_review_if_needed",
        lambda **kwargs: None,
    )

    status = main(["publish", "run", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    assert status == 0
    assert "Publish Result: published" in captured.out
    assert (
        "Publish URL: https://github.com/cracklings3d/markdown-pdf-renderer/pull/15"
        in captured.out
    )


def test_publish_run_resumes_post_publish_review_for_published_result(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {
                        "owner": "cracklings3d",
                        "repo": "markdown-pdf-renderer",
                        "number": 9,
                    },
                    "title": "[Enhancement] Add --version flag to CLI",
                    "body": "## Description\nAdd a version flag.",
                    "labels": ["enhancement"],
                    "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
                },
                "summary": "Add --version flag to CLI",
                "problem_statement": "Add a version flag.",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-plan.json").write_text(
        json.dumps(
            {
                "status": "draft_pr",
                "title": "Add --version flag to CLI",
                "body": "body",
                "reason_codes": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "status": "runnable",
                "created_at": "2026-04-27T00:00:00Z",
                "updated_at": "2026-04-27T00:00:00Z",
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-result.json").write_text(
        json.dumps(
            {
                "status": "published",
                "target": "draft_pr",
                "summary": "Published existing run.",
                "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            }
        ),
        encoding="utf-8",
    )

    review_calls: list[str] = []

    def fail_if_republish(*args, **kwargs):
        raise AssertionError("publish should not rerun for an already published result")

    def fake_review(**kwargs):
        review_calls.append(kwargs["publish_result"].url or "")
        return PostPublishReviewResult(
            status="approved",
            summary="Reviewer and architect approved the published pull request.",
            pull_request_url=kwargs["publish_result"].url,
            pull_number=13,
            reviewer_status="approved",
            reviewer_summary="Reviewer approved.",
            architect_status="approved",
            architect_summary="Architect approved.",
        )

    monkeypatch.setattr("precision_squad.cli.execute_publish_plan", fail_if_republish)
    monkeypatch.setattr("precision_squad.cli._run_post_publish_review_if_needed", fake_review)

    status = main(["publish", "run", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    review_payload = json.loads(
        (run_dir / "post-publish-review-result.json").read_text(encoding="utf-8")
    )

    assert status == 0
    assert review_calls == ["https://github.com/cracklings3d/markdown-pdf-renderer/pull/13"]
    assert "Publish Result: published" in captured.out
    assert "Publish URL: https://github.com/cracklings3d/markdown-pdf-renderer/pull/13" in captured.out
    assert "Post-Publish Review: approved" in captured.out
    assert review_payload["status"] == "approved"
    assert review_payload["pull_number"] == 13


def test_publish_run_retries_failed_post_publish_review(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {
                        "owner": "cracklings3d",
                        "repo": "markdown-pdf-renderer",
                        "number": 9,
                    },
                    "title": "[Enhancement] Add --version flag to CLI",
                    "body": "## Description\nAdd a version flag.",
                    "labels": ["enhancement"],
                    "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
                },
                "summary": "Add --version flag to CLI",
                "problem_statement": "Add a version flag.",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-plan.json").write_text(
        json.dumps(
            {
                "status": "draft_pr",
                "title": "Add --version flag to CLI",
                "body": "body",
                "reason_codes": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "status": "runnable",
                "created_at": "2026-04-27T00:00:00Z",
                "updated_at": "2026-04-27T00:00:00Z",
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-result.json").write_text(
        json.dumps(
            {
                "status": "published",
                "target": "draft_pr",
                "summary": "Published existing run.",
                "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "post-publish-review-result.json").write_text(
        json.dumps(
            {
                "status": "failed_infra",
                "summary": "Post-publish review could not complete successfully.",
                "pull_request_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "pull_number": 13,
                "reviewer_status": "failed_infra",
                "reviewer_summary": "Reviewer review agent could not produce a structured verdict.",
                "reviewer_feedback": [],
                "architect_status": "failed_infra",
                "architect_summary": "Architect review agent could not produce a structured verdict.",
                "architect_feedback": [],
                "issue_comment_url": None,
                "issue_reopened": False,
            }
        ),
        encoding="utf-8",
    )

    review_calls: list[str] = []

    def fail_if_republish(*args, **kwargs):
        raise AssertionError("publish should not rerun for an already published result")

    def fake_review(**kwargs):
        review_calls.append(kwargs["publish_result"].url or "")
        return PostPublishReviewResult(
            status="approved",
            summary="Reviewer and architect approved the published pull request.",
            pull_request_url=kwargs["publish_result"].url,
            pull_number=13,
            reviewer_status="approved",
            reviewer_summary="Reviewer approved.",
            architect_status="approved",
            architect_summary="Architect approved.",
        )

    monkeypatch.setattr("precision_squad.cli.execute_publish_plan", fail_if_republish)
    monkeypatch.setattr("precision_squad.cli._run_post_publish_review_if_needed", fake_review)

    status = main(["publish", "run", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    review_payload = json.loads(
        (run_dir / "post-publish-review-result.json").read_text(encoding="utf-8")
    )

    assert status == 0
    assert review_calls == ["https://github.com/cracklings3d/markdown-pdf-renderer/pull/13"]
    assert "Post-Publish Review: approved" in captured.out
    assert review_payload["status"] == "approved"


def test_publish_run_retries_stale_rejected_post_publish_review(
    capsys, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "issue-intake.json").write_text(
        json.dumps(
            {
                "issue": {
                    "reference": {
                        "owner": "cracklings3d",
                        "repo": "markdown-pdf-renderer",
                        "number": 9,
                    },
                    "title": "[Enhancement] Add --version flag to CLI",
                    "body": "## Description\nAdd a version flag.",
                    "labels": ["enhancement"],
                    "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
                },
                "summary": "Add --version flag to CLI",
                "problem_statement": "Add a version flag.",
                "assessment": {"status": "runnable", "reason_codes": []},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-plan.json").write_text(
        json.dumps(
            {
                "status": "draft_pr",
                "title": "Add --version flag to CLI",
                "body": "body",
                "reason_codes": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "run-123",
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "status": "runnable",
                "created_at": "2026-04-27T00:00:00Z",
                "updated_at": "2026-04-27T00:00:00Z",
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "publish-result.json").write_text(
        json.dumps(
            {
                "status": "published",
                "target": "draft_pr",
                "summary": "Published existing run.",
                "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "post-publish-review-result.json").write_text(
        json.dumps(
            {
                "status": "rejected",
                "summary": "Post-publish review rejected the pull request and reopened the issue.",
                "pull_request_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "pull_number": 13,
                "pull_head_sha": "old-sha",
                "reviewer_status": "rejected",
                "reviewer_summary": "Reviewer rejected.",
                "reviewer_feedback": ["old feedback"],
                "architect_status": "approved",
                "architect_summary": "Architect approved.",
                "architect_feedback": [],
                "issue_comment_url": "https://github.com/example/comment",
                "issue_reopened": True,
            }
        ),
        encoding="utf-8",
    )

    review_calls: list[str] = []

    def fail_if_republish(*args, **kwargs):
        raise AssertionError("publish should not rerun for an already published result")

    def fake_review(**kwargs):
        review_calls.append(kwargs["publish_result"].url or "")
        return PostPublishReviewResult(
            status="approved",
            summary="Reviewer and architect approved the published pull request.",
            pull_request_url=kwargs["publish_result"].url,
            pull_number=13,
            pull_head_sha="new-sha",
            reviewer_status="approved",
            reviewer_summary="Reviewer approved.",
            architect_status="approved",
            architect_summary="Architect approved.",
        )

    monkeypatch.setattr("precision_squad.cli.execute_publish_plan", fail_if_republish)
    monkeypatch.setattr("precision_squad.cli._run_post_publish_review_if_needed", fake_review)
    monkeypatch.setattr("precision_squad.cli._post_publish_review_is_stale", lambda intake, review_result: True)

    status = main(["publish", "run", "run-123", "--runs-dir", str(runs_dir)])

    captured = capsys.readouterr()
    review_payload = json.loads(
        (run_dir / "post-publish-review-result.json").read_text(encoding="utf-8")
    )

    assert status == 0
    assert review_calls == ["https://github.com/cracklings3d/markdown-pdf-renderer/pull/13"]
    assert "Post-Publish Review: approved" in captured.out
    assert review_payload["status"] == "approved"
    assert review_payload["pull_head_sha"] == "new-sha"
