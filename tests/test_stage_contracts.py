"""Tests for explicit downstream stage contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precision_squad.models import (
    ApprovedPlan,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    NamedReference,
    RunRecord,
)
from precision_squad.stage_contracts import (
    DOCS_CHECKLIST_SOURCE,
    load_developer_stage_contract,
    load_review_stage_contract,
    render_developer_approved_plan_context,
    render_review_prompt,
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
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-27T00:00:00Z",
        updated_at="2026-04-27T00:00:00Z",
        run_dir=str(run_dir),
    )


def _approved_plan() -> ApprovedPlan:
    return ApprovedPlan(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        plan_summary="Review the implementation against the approved plan.",
        implementation_steps=("Inspect the diff", "Verify the CLI output"),
        named_references=(
            NamedReference(
                name="src/precision_squad/cli.py",
                reference_type="file",
                description="CLI entry point",
            ),
        ),
        retrieval_surface_summary="src/precision_squad/cli.py, tests/test_cli.py",
        approved=True,
    )


def _write_approved_plan(run_dir: Path) -> None:
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Review the implementation against the approved plan.",
                "implementation_steps": ["Inspect the diff", "Verify the CLI output"],
                "named_references": [
                    {
                        "name": "src/precision_squad/cli.py",
                        "reference_type": "file",
                        "description": "CLI entry point",
                    }
                ],
                "retrieval_surface_summary": "src/precision_squad/cli.py, tests/test_cli.py",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )


def _write_developer_artifacts(run_dir: Path, contract_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    contract_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "issue.md").write_text("# Issue\n", encoding="utf-8")
    (run_dir / "executor.stdout.log").write_text("stdout\n", encoding="utf-8")
    (run_dir / "executor.stderr.log").write_text("stderr\n", encoding="utf-8")
    (contract_dir / "contract.json").write_text("{}\n", encoding="utf-8")
    (contract_dir / "README.snapshot.md").write_text("# Source: README.md\n", encoding="utf-8")


def test_load_developer_stage_contract_requires_allowlisted_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    contract_dir = run_dir / "execution-contract"
    _write_developer_artifacts(run_dir, contract_dir)

    contract = load_developer_stage_contract(
        approved_plan=_approved_plan(),
        intake=_intake(),
        run_record=_record(run_dir),
        run_dir=run_dir,
        contract_artifact_dir=contract_dir,
        repo_workspace=tmp_path / "workspace" / "repo",
    )

    assert contract.issue_statement_path == run_dir / "issue.md"
    assert contract.execution_contract_path == contract_dir / "contract.json"
    assert contract.readme_snapshot_path == contract_dir / "README.snapshot.md"
    assert contract.executor_stdout_path == run_dir / "executor.stdout.log"
    assert contract.executor_stderr_path == run_dir / "executor.stderr.log"


def test_load_developer_stage_contract_fails_when_required_artifact_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    contract_dir = run_dir / "execution-contract"
    _write_developer_artifacts(run_dir, contract_dir)
    (contract_dir / "README.snapshot.md").unlink()

    with pytest.raises(ValueError, match="README snapshot artifact"):
        load_developer_stage_contract(
            approved_plan=_approved_plan(),
            intake=_intake(),
            run_record=_record(run_dir),
            run_dir=run_dir,
            contract_artifact_dir=contract_dir,
            repo_workspace=tmp_path / "workspace" / "repo",
        )


def test_render_developer_approved_plan_context_uses_canonical_fields_only() -> None:
    lines = render_developer_approved_plan_context(_approved_plan())

    assert lines == [
        "Approved plan:",
        "- Summary: Review the implementation against the approved plan.",
        "- Implementation steps:",
        "  - Inspect the diff",
        "  - Verify the CLI output",
        "- Retrieval surface summary: src/precision_squad/cli.py, tests/test_cli.py",
        "- Named references:",
        "  - src/precision_squad/cli.py (file): CLI entry point",
    ]


def test_load_review_stage_contract_uses_deterministic_checklist_and_empty_decision_slot(
    tmp_path: Path,
) -> None:
    _write_approved_plan(tmp_path)

    contract = load_review_stage_contract(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
        pull_number=13,
        pull_head_sha="head-sha",
        diff_loader=lambda *args: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n",
    )

    assert contract.pull_number == 13
    assert contract.pull_head_sha == "head-sha"
    assert contract.checklist_rules[0]["code"] == "docs_entrypoint_present"
    assert contract.surfaced_design_decisions.startswith("none")


def test_render_review_prompt_includes_only_required_review_inputs(tmp_path: Path) -> None:
    _write_approved_plan(tmp_path)
    contract = load_review_stage_contract(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
        pull_number=13,
        pull_head_sha="head-sha",
        diff_loader=lambda *args: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n",
    )

    prompt = render_review_prompt("reviewer", contract)

    assert f"## Deterministic Review Checklist ({DOCS_CHECKLIST_SOURCE})" in prompt
    assert "docs_entrypoint_present" in prompt
    assert "## Surfaced Design Decisions" in prompt
    assert "reserved for issue #55" in prompt
    assert "PR Head SHA: head-sha" in prompt
    assert "## PR Diff" in prompt


def test_load_review_stage_contract_fails_when_checklist_loader_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_approved_plan(tmp_path)
    monkeypatch.setattr(
        "precision_squad.stage_contracts.load_review_checklist_rules",
        lambda: (_ for _ in ()).throw(ValueError("docs checklist field 'rules' must be a list")),
    )

    with pytest.raises(ValueError, match="docs checklist field 'rules' must be a list"):
        load_review_stage_contract(
            intake=_intake(),
            run_record=_record(tmp_path),
            run_dir=tmp_path,
            pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            pull_number=13,
            pull_head_sha="head-sha",
            diff_loader=lambda *args: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n",
        )
