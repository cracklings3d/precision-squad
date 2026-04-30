"""Integration tests: GitHub publishing path.

Tests the full RunCoordinator flow with real GitHub clients for read
operations, targeting cracklings3d/markdown-pdf-renderer.

publish=False tests: real GitHub issue context, dry_run result (no writes).
publish=True tests: real GitHub issue context, mocked publish executor (no real PRs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from precision_squad.coordinator import RepairIssueParams, RunCoordinator
from precision_squad.models import (
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    PublishResult,
)
from tests.integration.test_pipeline_approved import _ApprovedTestDependencies


def _runnable_intake() -> IssueIntake:
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


class _StubRepairAdapterForGithub:
    """Trivial repair adapter that appends a comment to __init__.py."""

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

        init_file = repo_workspace / "src" / "clean_pkg" / "__init__.py"
        if init_file.exists():
            original = init_file.read_text(encoding="utf-8")
            init_file.write_text(original + "# precision-squad: repaired\n", encoding="utf-8")

        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "test: trivial repair"],
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
            summary="Trivial repair: appended comment to __init__.py",
            detail_codes=("repair_stage_completed",),
            workspace_path=str(repo_workspace.parent),
            patch_path=str(patch_path),
        )


class _GithubPublishTestDependencies(_ApprovedTestDependencies):
    """Dependencies that use real GitHub read clients for the publishing path.

    publish=False: uses real execute_publish_plan (returns dry_run, no GitHub writes)
    publish=True: uses mocked execute_publish_plan (avoids real git/GitHub writes)
    """

    def __init__(self, adapter, real_issue_client) -> None:
        super().__init__(adapter)
        self._real_issue_client = real_issue_client

    def run_post_publish_review_if_needed(self, **kwargs):
        return None


@pytest.mark.integration
def test_publish_dry_run_returns_dry_run_status(
    make_clean_repo,
    real_github_issue_client,
    tmp_path: Path,
):
    """publish=False returns status=dry_run without calling GitHub write operations."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
    )

    adapter = _StubRepairAdapterForGithub()
    deps = _GithubPublishTestDependencies(adapter, real_github_issue_client)

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    assert report.publish_result is not None
    assert report.publish_result.status == "dry_run", (
        f"Expected dry_run, got {report.publish_result.status}: "
        f"{report.publish_result.summary}"
    )
    assert report.publish_plan.status == "draft_pr"
    assert report.exit_code == 0


@pytest.mark.integration
def test_publish_plan_contains_issue_reference_and_verdict(
    make_clean_repo,
    real_github_issue_client,
    tmp_path: Path,
):
    """Publish plan body includes issue reference, run ID, and governance verdict."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
    )

    adapter = _StubRepairAdapterForGithub()
    deps = _GithubPublishTestDependencies(adapter, real_github_issue_client)

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    plan = report.publish_plan
    assert "cracklings3d/markdown-pdf-renderer#9" in plan.body
    assert report.run_record.run_id in plan.body
    assert "approved" in plan.body.lower()


@pytest.mark.integration
def test_publish_true_calls_execute_publish_plan_with_publish_true(
    make_clean_repo,
    real_github_issue_client,
    tmp_path: Path,
):
    """With publish=True, execute_publish_plan is called with publish=True.

    This tests the coordinator wiring without actually creating real GitHub
    resources (git push, PR creation). The publish executor is mocked.
    """
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=True,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
    )

    adapter = _StubRepairAdapterForGithub()

    class _MockedPublishTestDependencies(_GithubPublishTestDependencies):
        def execute_publish_plan(self, intake, plan, *, publish, run_dir=None):
            assert publish is True, "execute_publish_plan should be called with publish=True"
            return PublishResult(
                status="published",
                target=plan.status,
                summary="Mocked: created draft pull request.",
                url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/999",
                branch_name="precision-squad/test-run",
                pull_number=999,
            )

    deps = _MockedPublishTestDependencies(adapter, real_github_issue_client)

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    assert report.publish_result is not None
    assert report.publish_result.status == "published"
    assert report.publish_result.url == "https://github.com/cracklings3d/markdown-pdf-renderer/pull/999"
    assert report.publish_result.pull_number == 999


@pytest.mark.integration
def test_publish_result_persisted_in_run_store(
    make_clean_repo,
    real_github_issue_client,
    tmp_path: Path,
):
    """Publish result is written to the run store by the coordinator."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    params = RepairIssueParams(
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        runs_dir=runs_dir,
        repo_path=make_clean_repo,
        publish=False,
        repair_agent="opencode",
        repair_model=None,
        review_model=None,
    )

    adapter = _StubRepairAdapterForGithub()
    deps = _GithubPublishTestDependencies(adapter, real_github_issue_client)

    report = RunCoordinator().repair_issue(
        params=params,
        intake=_runnable_intake(),
        dependencies=deps,
    )

    from precision_squad.run_store import RunStore

    stored = RunStore(runs_dir).read_publish_result(Path(report.run_record.run_dir))
    assert stored is not None
    assert stored.status == "dry_run"
