"""Minimal PAT-backed GitHub issue client."""

from __future__ import annotations

import json
import os
import subprocess
from abc import ABC, abstractmethod
from urllib import error as urllib_error
from urllib import request as urllib_request

from .docs_remediation import (
    DOCS_REMEDIATION_MARKER,
    extract_docs_blocker_findings,
    extract_docs_blocker_fingerprint,
    normalize_docs_findings,
)
from .github_transport import GitHubTransportResolution, resolve_github_transport
from .models import GitHubIssue, IssueReference


class GitHubClientError(RuntimeError):
    """Raised when GitHub issue fetches cannot be completed."""


class GitHubRuntimeTransport(ABC):
    """Private runtime transport boundary selected once per client."""

    @abstractmethod
    def fetch_issue(self, reference: IssueReference) -> dict[str, object]:
        """Fetch a single issue payload from the transport."""

    @abstractmethod
    def fetch_issue_comments(self, reference: IssueReference) -> list[dict[str, object]]:
        """Fetch comments for a single issue from the transport."""

    @abstractmethod
    def create_issue_comment(self, reference: IssueReference, body: str) -> str:
        """Create an issue comment and return its HTML URL."""

    @abstractmethod
    def create_issue(self, owner: str, repo: str, *, title: str, body: str) -> str:
        """Create an issue and return its HTML URL."""

    @abstractmethod
    def list_repo_issues(self, owner: str, repo: str) -> list[dict[str, object]]:
        """List open issues for a repository."""

    @abstractmethod
    def create_draft_pull_request(
        self,
        reference: IssueReference,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> str:
        """Create a draft pull request and return its HTML URL."""

    @abstractmethod
    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, object]:
        """Get a pull request payload."""

    @abstractmethod
    def update_pull_request(
        self, owner: str, repo: str, pull_number: int, *, title: str, body: str
    ) -> str:
        """Update a pull request title/body and return its HTML URL."""

    @abstractmethod
    def patch_pull_request(self, owner: str, repo: str, pull_number: int, payload: dict) -> None:
        """Patch a pull request with arbitrary payload."""

    @abstractmethod
    def reopen_issue(self, reference: IssueReference) -> None:
        """Reopen a closed issue."""

    @abstractmethod
    def close_issue(self, reference: IssueReference) -> None:
        """Close an open issue."""

    @abstractmethod
    def merge_pull_request(self, owner: str, repo: str, pull_number: int) -> None:
        """Merge an open pull request."""

    @abstractmethod
    def close_pull_request(self, owner: str, repo: str, pull_number: int) -> None:
        """Close an open pull request."""

    @abstractmethod
    def update_pull_request_branch(
        self, owner: str, repo: str, pull_number: int
    ) -> None:
        """Update a pull request branch with latest base changes."""


class GitHubMcpTransportStrategy(GitHubRuntimeTransport):
    """MCP-based GitHub transport - not yet implemented."""

    def fetch_issue(self, reference: IssueReference) -> dict[str, object]:
        raise NotImplementedError("MCP transport not implemented for fetch_issue")

    def fetch_issue_comments(self, reference: IssueReference) -> list[dict[str, object]]:
        raise NotImplementedError("MCP transport not implemented for fetch_issue_comments")

    def create_issue_comment(self, reference: IssueReference, body: str) -> str:
        raise NotImplementedError("MCP transport not implemented for create_issue_comment")

    def create_issue(self, owner: str, repo: str, *, title: str, body: str) -> str:
        raise NotImplementedError("MCP transport not implemented for create_issue")

    def list_repo_issues(self, owner: str, repo: str) -> list[dict[str, object]]:
        raise NotImplementedError("MCP transport not implemented for list_repo_issues")

    def create_draft_pull_request(
        self,
        reference: IssueReference,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> str:
        raise NotImplementedError("MCP transport not implemented for create_draft_pull_request")

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, object]:
        raise NotImplementedError("MCP transport not implemented for get_pull_request")

    def update_pull_request(
        self, owner: str, repo: str, pull_number: int, *, title: str, body: str
    ) -> str:
        raise NotImplementedError("MCP transport not implemented for update_pull_request")

    def patch_pull_request(self, owner: str, repo: str, pull_number: int, payload: dict) -> None:
        raise NotImplementedError("MCP transport not implemented for patch_pull_request")

    def reopen_issue(self, reference: IssueReference) -> None:
        raise NotImplementedError("MCP transport not implemented for reopen_issue")

    def close_issue(self, reference: IssueReference) -> None:
        raise NotImplementedError("MCP transport not implemented for close_issue")

    def merge_pull_request(self, owner: str, repo: str, pull_number: int) -> None:
        raise NotImplementedError("MCP transport not implemented for merge_pull_request")

    def close_pull_request(self, owner: str, repo: str, pull_number: int) -> None:
        raise NotImplementedError("MCP transport not implemented for close_pull_request")

    def update_pull_request_branch(
        self, owner: str, repo: str, pull_number: int
    ) -> None:
        raise NotImplementedError("MCP transport not implemented for update_pull_request_branch")


class GitHubCliTransportStrategy(GitHubRuntimeTransport):
    """gh CLI-based GitHub transport using existing _via_gh helpers."""

    def __init__(self, token: str) -> None:
        self._token = token

    def fetch_issue(self, reference: IssueReference) -> dict[str, object]:
        """Fetch issue via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{reference.owner}/{reference.repo}/issues/{reference.number}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub issue fetch failed for {reference}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub issue fetch failed for {reference}: gh CLI returned {completed.returncode}"
            )

        return json.loads(completed.stdout)

    def fetch_issue_comments(self, reference: IssueReference) -> list[dict[str, object]]:
        """Fetch issue comments via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{reference.owner}/{reference.repo}/issues/{reference.number}/comments",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub issue comments fetch failed for {reference}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub issue comments fetch failed for {reference}: gh CLI returned {completed.returncode}"
            )

        payload = json.loads(completed.stdout)
        if not isinstance(payload, list):
            raise GitHubClientError(f"GitHub issue comments payload for {reference} is invalid.")
        return payload

    def create_issue_comment(self, reference: IssueReference, body: str) -> str:
        """Create issue comment via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{reference.owner}/{reference.repo}/issues/{reference.number}/comments",
                    "--method",
                    "POST",
                    "-f",
                    f"body={body}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub comment create failed for {reference}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub comment create failed for {reference}: gh CLI returned {completed.returncode}"
            )

        payload = json.loads(completed.stdout)
        html_url = payload.get("html_url")
        if not isinstance(html_url, str):
            raise GitHubClientError("GitHub comment response did not include html_url.")
        return html_url

    def create_issue(self, owner: str, repo: str, *, title: str, body: str) -> str:
        """Create issue via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{repo}/issues",
                    "--method",
                    "POST",
                    "-f",
                    f"title={title}",
                    "-f",
                    f"body={body}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub issue create failed for {owner}/{repo}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub issue create failed for {owner}/{repo}: gh CLI returned {completed.returncode}"
            )

        payload = json.loads(completed.stdout)
        html_url = payload.get("html_url")
        if not isinstance(html_url, str):
            raise GitHubClientError("GitHub issue response did not include html_url.")
        return html_url

    def list_repo_issues(self, owner: str, repo: str) -> list[dict[str, object]]:
        """List repository issues via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{repo}/issues?state=open&per_page=100",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub issue list fetch failed for {owner}/{repo}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub issue list fetch failed for {owner}/{repo}: gh CLI returned {completed.returncode}"
            )

        payload = json.loads(completed.stdout)
        if not isinstance(payload, list):
            raise GitHubClientError(f"GitHub issue list payload for {owner}/{repo} is invalid.")
        return payload

    def create_draft_pull_request(
        self,
        reference: IssueReference,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> str:
        """Create draft PR via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{reference.owner}/{reference.repo}/pulls",
                    "--method",
                    "POST",
                    "-f",
                    f"title={title}",
                    "-f",
                    f"body={body}",
                    "-f",
                    f"head={head}",
                    "-f",
                    f"base={base}",
                    "-f",
                    "draft=true",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub draft PR create failed for {reference}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub draft PR create failed for {reference}: gh CLI returned {completed.returncode}"
            )

        payload = json.loads(completed.stdout)
        html_url = payload.get("html_url")
        if not isinstance(html_url, str):
            raise GitHubClientError("GitHub pull request response did not include html_url.")
        return html_url

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, object]:
        """Get pull request via gh CLI."""
        try:
            completed = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pull_number}"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub PR fetch failed for {owner}/{repo}/{pull_number}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub PR fetch failed for {owner}/{repo}/{pull_number}: gh CLI returned {completed.returncode}"
            )

        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict):
            raise GitHubClientError(f"GitHub PR payload for {owner}/{repo}/{pull_number} is invalid.")
        return payload

    def update_pull_request(
        self, owner: str, repo: str, pull_number: int, *, title: str, body: str
    ) -> str:
        """Update PR title/body via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{repo}/pulls/{pull_number}",
                    "--method",
                    "PATCH",
                    "-f",
                    f"title={title}",
                    "-f",
                    f"body={body}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub PR update failed for {owner}/{repo}/{pull_number}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub PR update failed for {owner}/{repo}/{pull_number}: gh CLI returned {completed.returncode}"
            )

        payload = json.loads(completed.stdout)
        html_url = payload.get("html_url")
        if not isinstance(html_url, str):
            raise GitHubClientError("GitHub pull request response did not include html_url.")
        return html_url

    def patch_pull_request(self, owner: str, repo: str, pull_number: int, payload: dict) -> None:
        """Patch PR with arbitrary payload via gh CLI."""
        state = payload.get("state")
        draft = payload.get("draft")
        try:
            cmd = [
                "gh",
                "api",
                f"repos/{owner}/{repo}/pulls/{pull_number}",
                "--method",
                "PATCH",
            ]
            if state is not None:
                cmd.extend(["-f", f"state={state}"])
            if draft is not None:
                cmd.extend(["-f", f"draft={str(draft).lower()}"])
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub PR patch failed for {owner}/{repo}/{pull_number}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub PR patch failed for {owner}/{repo}/{pull_number}: gh CLI returned {completed.returncode}"
            )

    def reopen_issue(self, reference: IssueReference) -> None:
        """Reopen issue via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{reference.owner}/{reference.repo}/issues/{reference.number}",
                    "--method",
                    "PATCH",
                    "-f",
                    "state=open",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub issue reopen failed for {reference}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub issue reopen failed for {reference}: gh CLI returned {completed.returncode}"
            )

    def close_issue(self, reference: IssueReference) -> None:
        """Close issue via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{reference.owner}/{reference.repo}/issues/{reference.number}",
                    "--method",
                    "PATCH",
                    "-f",
                    "state=closed",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub issue close failed for {reference}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub issue close failed for {reference}: gh CLI returned {completed.returncode}"
            )

    def merge_pull_request(self, owner: str, repo: str, pull_number: int) -> None:
        """Merge PR via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{repo}/pulls/{pull_number}/merge",
                    "--method",
                    "PUT",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub PR merge failed for {owner}/{repo}/{pull_number}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            if "409" in completed.stderr or "already been merged" in completed.stderr.lower():
                return
            raise GitHubClientError(
                f"GitHub PR merge failed for {owner}/{repo}/{pull_number}: gh CLI returned {completed.returncode}"
            )

    def close_pull_request(self, owner: str, repo: str, pull_number: int) -> None:
        """Close PR via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{repo}/pulls/{pull_number}",
                    "--method",
                    "PATCH",
                    "-f",
                    "state=closed",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub PR close failed for {owner}/{repo}/{pull_number}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            if "405" in completed.stderr or "Cannot change" in completed.stderr:
                return
            raise GitHubClientError(
                f"GitHub PR close failed for {owner}/{repo}/{pull_number}: gh CLI returned {completed.returncode}"
            )

    def update_pull_request_branch(
        self, owner: str, repo: str, pull_number: int
    ) -> None:
        """Update PR branch via gh CLI."""
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{repo}/pulls/{pull_number}/updateBranch",
                    "--method",
                    "PUT",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GitHubClientError(
                f"GitHub PR branch update failed for {owner}/{repo}/{pull_number}: gh CLI unavailable"
            ) from exc

        if completed.returncode != 0:
            raise GitHubClientError(
                f"GitHub PR branch update failed for {owner}/{repo}/{pull_number}: gh CLI returned {completed.returncode}"
            )


def _build_strategy(
    resolution: GitHubTransportResolution, token: str
) -> GitHubRuntimeTransport:
    """Build the appropriate strategy based on transport resolution."""
    selected = resolution.selected_transport
    if selected == "mcp":
        return GitHubMcpTransportStrategy()
    if selected == "cli":
        return GitHubCliTransportStrategy(token)
    raise GitHubClientError(f"Unknown transport selected: {selected}")


class GitHubIssueClient:
    """Fetch issue data from the GitHub REST API."""

    def __init__(
        self,
        token: str,
        *,
        strategy: GitHubRuntimeTransport,
        transport_resolution: GitHubTransportResolution | None = None,
    ) -> None:
        self._token = token
        self._strategy = strategy
        self.transport_resolution = transport_resolution

    @classmethod
    def from_env(cls, token_env: str = "GITHUB_TOKEN") -> "GitHubIssueClient":
        token = os.getenv(token_env)
        if not token:
            raise GitHubClientError(
                f"Missing GitHub token. Set the {token_env} environment variable."
            )
        resolution = resolve_github_transport()
        strategy = _build_strategy(resolution, token)
        return cls(token, strategy=strategy, transport_resolution=resolution)

    def fetch_issue(self, reference: IssueReference) -> GitHubIssue:
        payload = self._strategy.fetch_issue(reference)
        comments_payload = self._strategy.fetch_issue_comments(reference)

        if "pull_request" in payload:
            raise GitHubClientError(f"{reference} refers to a pull request, not an issue.")

        raw_labels = payload.get("labels")
        labels: tuple[str, ...] = ()
        if isinstance(raw_labels, list):
            collected: list[str] = []
            for label in raw_labels:
                if isinstance(label, dict):
                    name = label.get("name")
                    if isinstance(name, str):
                        collected.append(name)
            labels = tuple(collected)

        raw_title = payload.get("title")
        raw_body = payload.get("body")
        raw_html_url = payload.get("html_url")
        if not isinstance(raw_title, str) or not isinstance(raw_html_url, str):
            raise GitHubClientError(f"GitHub issue payload for {reference} is missing fields.")

        body = raw_body if isinstance(raw_body, str) else ""
        comments = _extract_issue_comments(comments_payload)

        return GitHubIssue(
            reference=reference,
            title=raw_title,
            body=body,
            labels=labels,
            html_url=raw_html_url,
            comments=comments,
        )


class GitHubWriteClient:
    """Minimal PAT-backed GitHub write client."""

    def __init__(
        self,
        token: str,
        *,
        strategy: GitHubRuntimeTransport,
        transport_resolution: GitHubTransportResolution | None = None,
    ) -> None:
        self._token = token
        self._strategy = strategy
        self.transport_resolution = transport_resolution

    @classmethod
    def from_env(cls, token_env: str = "GITHUB_TOKEN") -> "GitHubWriteClient":
        token = os.getenv(token_env)
        if not token:
            raise GitHubClientError(
                f"Missing GitHub token. Set the {token_env} environment variable."
            )
        resolution = resolve_github_transport()
        strategy = _build_strategy(resolution, token)
        return cls(token, strategy=strategy, transport_resolution=resolution)

    def create_issue_comment(self, reference: IssueReference, body: str) -> str:
        return self._strategy.create_issue_comment(reference, body)

    def create_issue(self, owner: str, repo: str, *, title: str, body: str) -> str:
        return self._strategy.create_issue(owner, repo, title=title, body=body)

    def find_open_docs_remediation_issue(
        self,
        owner: str,
        repo: str,
        *,
        blocker_fingerprint: str,
        blocker_findings: list[dict[str, str]] | None = None,
        exclude_issue_number: int | None = None,
    ) -> tuple[int, str] | None:
        payload = self._strategy.list_repo_issues(owner, repo)

        normalized_findings = normalize_docs_findings(blocker_findings or [])
        for item in payload:
            if not isinstance(item, dict) or "pull_request" in item:
                continue
            number = item.get("number")
            html_url = item.get("html_url")
            body = item.get("body")
            if not isinstance(number, int) or not isinstance(html_url, str):
                continue
            if exclude_issue_number is not None and number == exclude_issue_number:
                continue
            body_text = body if isinstance(body, str) else ""
            if DOCS_REMEDIATION_MARKER not in body_text:
                continue
            if normalized_findings:
                existing_findings = extract_docs_blocker_findings(body_text)
                if existing_findings == normalized_findings:
                    return number, html_url
            if extract_docs_blocker_fingerprint(body_text) != blocker_fingerprint:
                continue
            return number, html_url
        return None

    def create_draft_pull_request(
        self,
        reference: IssueReference,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> str:
        return self._strategy.create_draft_pull_request(reference, title, body, head, base)

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, object]:
        return self._strategy.get_pull_request(owner, repo, pull_number)

    def update_pull_request(
        self, owner: str, repo: str, pull_number: int, *, title: str, body: str
    ) -> str:
        return self._strategy.update_pull_request(owner, repo, pull_number, title=title, body=body)

    def mark_pull_request_ready(self, owner: str, repo: str, pull_number: int) -> None:
        self._strategy.patch_pull_request(owner, repo, pull_number, {"draft": False})

    def get_pull_request_head_branch(self, owner: str, repo: str, pull_number: int) -> str | None:
        payload = self.get_pull_request(owner, repo, pull_number)
        head = payload.get("head")
        if not isinstance(head, dict):
            return None
        ref = head.get("ref")
        return ref if isinstance(ref, str) else None

    def get_pull_request_head_sha(self, owner: str, repo: str, pull_number: int) -> str | None:
        payload = self.get_pull_request(owner, repo, pull_number)
        return _extract_pull_head_sha(payload)

    def reopen_issue(self, reference: IssueReference) -> None:
        self._strategy.reopen_issue(reference)

    def close_issue(self, reference: IssueReference) -> None:
        self._strategy.close_issue(reference)

    def merge_pull_request(self, owner: str, repo: str, pull_number: int) -> None:
        self._strategy.merge_pull_request(owner, repo, pull_number)

    def close_pull_request(self, owner: str, repo: str, pull_number: int) -> None:
        self._strategy.close_pull_request(owner, repo, pull_number)

    def update_pull_request_branch(
        self, owner: str, repo: str, pull_number: int
    ) -> None:
        self._strategy.update_pull_request_branch(owner, repo, pull_number)


def _extract_issue_comments(payload: list[dict[str, object]] | None) -> tuple[str, ...]:
    if payload is None:
        return ()

    comments: list[str] = []
    for item in payload:
        body = item.get("body")
        if isinstance(body, str) and body.strip():
            comments.append(body)
    return tuple(comments)


def _extract_pull_head_sha(payload: dict[str, object]) -> str | None:
    head = payload.get("head")
    if not isinstance(head, dict):
        return None
    sha = head.get("sha")
    return sha if isinstance(sha, str) else None
