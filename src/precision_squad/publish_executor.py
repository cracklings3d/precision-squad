"""Execute publish plans against GitHub or as dry runs."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .docs_remediation import extract_docs_blocker_findings, extract_docs_blocker_fingerprint
from .github_client import GitHubClientError, GitHubWriteClient
from .models import IssueIntake, PublishPlan, PublishResult


def execute_publish_plan(
    intake: IssueIntake,
    plan: PublishPlan,
    *,
    publish: bool,
    token_env: str = "GITHUB_TOKEN",
    run_dir: Path | None = None,
) -> PublishResult:
    """Execute or preview a publish plan."""
    if not publish:
        return PublishResult(
            status="dry_run",
            target=plan.status,
            summary="Publish plan prepared but not sent. Re-run with --publish to write to GitHub.",
            url=None,
            branch_name=plan.branch_name,
            pull_number=plan.pull_number,
        )

    client = GitHubWriteClient.from_env(token_env)
    if plan.status == "issue_comment":
        url = client.create_issue_comment(intake.issue.reference, plan.body)
        return PublishResult(
            status="published",
            target=plan.status,
            summary="Posted blocked-run issue comment to GitHub.",
            url=url,
            branch_name=plan.branch_name,
            pull_number=plan.pull_number,
        )

    if plan.status == "follow_up_issue":
        blocker_fingerprint = extract_docs_blocker_fingerprint(plan.body)
        if blocker_fingerprint is not None:
            blocker_findings = extract_docs_blocker_findings(plan.body)
            existing_issue = client.find_open_docs_remediation_issue(
                intake.issue.reference.owner,
                intake.issue.reference.repo,
                blocker_fingerprint=blocker_fingerprint,
                blocker_findings=blocker_findings,
                exclude_issue_number=intake.issue.reference.number,
            )
            if existing_issue is not None:
                _, url = existing_issue
                return PublishResult(
                    status="published",
                    target=plan.status,
                    summary="Reused existing follow-up issue instead of creating a duplicate.",
                    url=url,
                    branch_name=plan.branch_name,
                    pull_number=plan.pull_number,
                )
        url = client.create_issue(
            intake.issue.reference.owner,
            intake.issue.reference.repo,
            title=plan.title,
            body=plan.body,
        )
        return PublishResult(
            status="published",
            target=plan.status,
            summary="Created follow-up issue for a repo-level blocker.",
            url=url,
            branch_name=plan.branch_name,
            pull_number=plan.pull_number,
        )

    url, branch_name, pull_number = _publish_draft_pull_request(
        intake, plan, client, run_dir=run_dir, token_env=token_env
    )
    return PublishResult(
        status="published",
        target=plan.status,
        summary=(
            "Updated existing pull request from the stored repair workspace."
            if pull_number is not None and plan.pull_number == pull_number
            else "Created draft pull request from the stored repair workspace."
        ),
        url=url,
        branch_name=branch_name,
        pull_number=pull_number,
    )


def _publish_draft_pull_request(
    intake: IssueIntake,
    plan: PublishPlan,
    client: GitHubWriteClient,
    *,
    run_dir: Path | None,
    token_env: str,
) -> tuple[str, str, int | None]:
    if run_dir is None:
        raise GitHubClientError("Draft PR publishing requires a stored run directory.")

    source_repo_dir = run_dir / "repair-workspace" / "repo"
    if not source_repo_dir.exists():
        raise GitHubClientError(
            "Draft PR publishing requires the stored repair workspace, but it was not found."
        )

    repo_dir = _prepare_publish_workspace(run_dir, source_repo_dir)

    token = os.getenv(token_env)
    if not token:
        raise GitHubClientError(
            f"Missing GitHub token. Set the {token_env} environment variable."
        )

    branch_name = plan.branch_name or f"precision-squad/{run_dir.name}"
    pull_number = plan.pull_number
    if pull_number is not None:
        existing_branch = client.get_pull_request_head_branch(
            intake.issue.reference.owner,
            intake.issue.reference.repo,
            pull_number,
        )
        if existing_branch:
            branch_name = existing_branch
    base_branch = _resolve_base_branch(repo_dir)
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_NAME": "precision-squad",
            "GIT_AUTHOR_EMAIL": "precision-squad@local",
            "GIT_COMMITTER_NAME": "precision-squad",
            "GIT_COMMITTER_EMAIL": "precision-squad@local",
        }
    )

    _run_git_command(["git", "checkout", "-B", branch_name], repo_dir, env=commit_env)
    _run_git_command(["git", "add", "-A"], repo_dir, env=commit_env)
    _run_git_command(["git", "commit", "-m", plan.title], repo_dir, env=commit_env)

    push_url = (
        f"https://x-access-token:{token}@github.com/"
        f"{intake.issue.reference.owner}/{intake.issue.reference.repo}.git"
    )
    _run_git_command(
        ["git", "push", "-u", push_url, f"HEAD:refs/heads/{branch_name}"],
        repo_dir,
        env=commit_env,
        redact=token,
    )
    if pull_number is not None:
        url = client.update_pull_request(
            intake.issue.reference.owner,
            intake.issue.reference.repo,
            pull_number,
            title=plan.title,
            body=plan.body,
        )
        client.mark_pull_request_ready(
            intake.issue.reference.owner,
            intake.issue.reference.repo,
            pull_number,
        )
        return url, branch_name, pull_number

    url = client.create_draft_pull_request(
        intake.issue.reference,
        title=plan.title,
        body=plan.body,
        head=branch_name,
        base=base_branch,
    )
    return url, branch_name, None


def _prepare_publish_workspace(run_dir: Path, source_repo_dir: Path) -> Path:
    publish_workspace = (run_dir / "publish-workspace").resolve()
    if publish_workspace.exists():
        shutil.rmtree(publish_workspace)
    shutil.copytree(source_repo_dir, publish_workspace)

    for relative_path in (
        Path(".pytest_cache"),
    ):
        candidate = publish_workspace / relative_path
        if candidate.exists():
            if candidate.is_dir():
                shutil.rmtree(candidate)
            else:
                candidate.unlink()

    for egg_info in publish_workspace.rglob("*.egg-info"):
        if egg_info.is_dir():
            shutil.rmtree(egg_info)

    for pycache in publish_workspace.rglob("__pycache__"):
        shutil.rmtree(pycache)
    for pyc in publish_workspace.rglob("*.pyc"):
        pyc.unlink()

    return publish_workspace


def _resolve_base_branch(repo_dir: Path) -> str:
    completed = subprocess.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        remote_ref = completed.stdout.strip()
        if remote_ref.startswith("origin/"):
            return remote_ref.removeprefix("origin/")

    fallback = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
    )
    if fallback.returncode == 0:
        return fallback.stdout.strip()
    return "main"


def _run_git_command(
    command: list[str],
    repo_dir: Path,
    *,
    env: dict[str, str],
    redact: str | None = None,
) -> None:
    completed = subprocess.run(
        command,
        cwd=str(repo_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return

    stderr = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
    if redact:
        stderr = stderr.replace(redact, "***")
    raise GitHubClientError(stderr)
