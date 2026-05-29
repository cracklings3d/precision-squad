"""Integration coverage for the repair issue CLI subprocess boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.support import approved_plan_for


@pytest.fixture(autouse=True)
def _require_explicit_integration_marker_selection(request: pytest.FixtureRequest) -> None:
    """Keep this subprocess slice out of plain default pytest runs."""

    markexpr = (request.config.option.markexpr or "").strip()
    if markexpr != "integration":
        pytest.skip("run this subprocess slice via the documented `pytest -m integration` path")


@pytest.mark.integration
def test_repair_issue_cli_subprocess_persists_implementation_stage_artifacts(
    make_clean_repo: Path,
    tmp_path: Path,
) -> None:
    if not (os.getenv("GITHUB_TOKEN") or os.getenv("OpenCode_Github_Token")):
        pytest.skip("GitHub token is not set (checked OpenCode_Github_Token, then GITHUB_TOKEN)")

    repo_root = Path(__file__).resolve().parents[2]
    runs_dir = tmp_path / "runs"
    approved_plan_path = tmp_path / "approved-plan.json"
    approved_plan = approved_plan_for("cracklings3d/markdown-pdf-renderer#9")
    approved_plan_path.write_text(
        json.dumps(
            {
                "issue_ref": approved_plan.issue_ref,
                "plan_summary": approved_plan.plan_summary,
                "implementation_steps": list(approved_plan.implementation_steps),
                "named_references": list(approved_plan.named_references),
                "retrieval_surface_summary": approved_plan.retrieval_surface_summary,
                "approved": approved_plan.approved,
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{repo_root / 'src'}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(repo_root / "src")
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "precision_squad.cli",
            "repair",
            "issue",
            "cracklings3d/markdown-pdf-renderer#9",
            "--repo-path",
            str(make_clean_repo),
            "--runs-dir",
            str(runs_dir),
            "--repair-agent",
            "none",
            "--approved-plan-path",
            str(approved_plan_path),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 4, completed.stdout + completed.stderr

    stdout_lines = completed.stdout.splitlines()
    run_dir_line = next(line for line in stdout_lines if line.startswith("Run Dir:"))
    run_dir = Path(run_dir_line.removeprefix("Run Dir:").strip())

    assert f"Run Dir: {run_dir}" in completed.stdout
    assert "Repair Status: not_configured" in completed.stdout
    assert "QA Status: not_run" in completed.stdout
    assert "Governance: blocked" in completed.stdout

    for artifact_name in (
        "approved-plan.json",
        "plan-review.json",
        "execution-result.json",
        "repair-result.json",
        "qa-baseline-result.json",
        "qa-result.json",
        "evaluation-result.json",
        "governance-verdict.json",
    ):
        assert (run_dir / artifact_name).exists(), artifact_name
