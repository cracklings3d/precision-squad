"""Minimal PAT-backed GitHub issue client."""

from __future__ import annotations

import json
import os
import subprocess
from urllib import error as urllib_error
from urllib import request as urllib_request

from .docs_remediation import (
    DOCS_REMEDIATION_MARKER,
    extract_docs_blocker_findings,
    extract_docs_blocker_fingerprint,
    normalize_docs_findings,
)
from .models import GitHubIssue, IssueReference


class GitHubClientError(RuntimeError):
    """Raised when GitHub issue fetches cannot be completed."""


class GitHubIssueClient:
    """Fetch issue data from the GitHub REST API."""

    def __init__(self, token: str) -> None:
        self._token = token

    @classmethod
    def from_env(cls, token_env: str = "GITHUB_TOKEN") -> "GitHubIssueClient":
        token = os.getenv(token_env)
        if not token:
            raise GitHubClientError(
                f"Missing GitHub token. Set the {token_env} environment variable."
            )
        return cls(token)

    def fetch_issue(self, reference: IssueReference) -> GitHubIssue:
        payload = self._fetch_issue_via_gh(reference)
        if payload is None:
            payload = self._fetch_issue_via_http(reference)
        comments_payload = self._fetch_issue_comments_via_gh(reference)
        if comments_payload is None:
            comments_payload = self._fetch_issue_comments_via_http(reference)

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

    def _fetch_issue_via_gh(self, reference: IssueReference) -> dict[str, object] | None:
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
        except OSError:
            return None

        if completed.returncode != 0:
            return None

        return json.loads(completed.stdout)

    def _fetch_issue_via_http(self, reference: IssueReference) -> dict[str, object]:
        request = urllib_request.Request(
            url=(
                f"https://api.github.com/repos/{reference.owner}/"
                f"{reference.repo}/issues/{reference.number}"
            ),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "precision-squad",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        try:
            with urllib_request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubClientError(
                f"GitHub issue fetch failed for {reference}: HTTP {exc.code}. {detail}"
            ) from exc
        except urllib_error.URLError as exc:
            raise GitHubClientError(
                f"GitHub issue fetch failed for {reference}: {exc.reason}"
            ) from exc

    def _fetch_issue_comments_via_gh(
        self, reference: IssueReference
    ) -> list[dict[str, object]] | None:
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
        except OSError:
            return None

        if completed.returncode != 0:
            return None

        payload = json.loads(completed.stdout)
        return payload if isinstance(payload, list) else None

    def _fetch_issue_comments_via_http(self, reference: IssueReference) -> list[dict[str, object]]:
        request = urllib_request.Request(
            url=(
                f"https://api.github.com/repos/{reference.owner}/"
                f"{reference.repo}/issues/{reference.number}/comments"
            ),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "precision-squad",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        try:
            with urllib_request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubClientError(
                f"GitHub issue comments fetch failed for {reference}: HTTP {exc.code}. {detail}"
            ) from exc
        except urllib_error.URLError as exc:
            raise GitHubClientError(
                f"GitHub issue comments fetch failed for {reference}: {exc.reason}"
            ) from exc

        if not isinstance(payload, list):
            raise GitHubClientError(f"GitHub issue comments payload for {reference} is invalid.")
        return payload


class GitHubWriteClient:
    """Minimal PAT-backed GitHub write client."""

    def __init__(self, token: str) -> None:
        self._token = token

    @classmethod
    def from_env(cls, token_env: str = "GITHUB_TOKEN") -> "GitHubWriteClient":
        token = os.getenv(token_env)
        if not token:
            raise GitHubClientError(
                f"Missing GitHub token. Set the {token_env} environment variable."
            )
        return cls(token)

    def create_issue_comment(self, reference: IssueReference, body: str) -> str:
        gh_url = self._create_issue_comment_via_gh(reference, body)
        if gh_url is not None:
            return gh_url

        payload = self._request_json(
            method="POST",
            url=(
                f"https://api.github.com/repos/{reference.owner}/"
                f"{reference.repo}/issues/{reference.number}/comments"
            ),
            payload={"body": body},
        )
        html_url = payload.get("html_url")
        if not isinstance(html_url, str):
            raise GitHubClientError("GitHub comment response did not include html_url.")
        return html_url

    def create_issue(self, owner: str, repo: str, *, title: str, body: str) -> str:
        gh_url = self._create_issue_via_gh(owner, repo, title=title, body=body)
        if gh_url is not None:
            return gh_url

        payload = self._request_json(
            method="POST",
            url=f"https://api.github.com/repos/{owner}/{repo}/issues",
            payload={"title": title, "body": body},
        )
        html_url = payload.get("html_url")
        if not isinstance(html_url, str):
            raise GitHubClientError("GitHub issue response did not include html_url.")
        return html_url

    def find_open_docs_remediation_issue(
        self,
        owner: str,
        repo: str,
        *,
        blocker_fingerprint: str,
        blocker_findings: list[dict[str, str]] | None = None,
        exclude_issue_number: int | None = None,
    ) -> tuple[int, str] | None:
        payload = self._list_repo_issues_via_gh(owner, repo)
        if payload is None:
            payload = self._list_repo_issues_via_http(owner, repo)

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

    def _create_issue_comment_via_gh(self, reference: IssueReference, body: str) -> str | None:
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
        except OSError:
            return None

        if completed.returncode != 0:
            return None

        payload = json.loads(completed.stdout)
        html_url = payload.get("html_url")
        return html_url if isinstance(html_url, str) else None

    def _list_repo_issues_via_gh(self, owner: str, repo: str) -> list[dict[str, object]] | None:
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
        except OSError:
            return None

        if completed.returncode != 0:
            return None

        payload = json.loads(completed.stdout)
        return payload if isinstance(payload, list) else None

    def _create_issue_via_gh(
        self, owner: str, repo: str, *, title: str, body: str
    ) -> str | None:
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
        except OSError:
            return None

        if completed.returncode != 0:
            return None

        payload = json.loads(completed.stdout)
        html_url = payload.get("html_url")
        return html_url if isinstance(html_url, str) else None

    def create_draft_pull_request(
        self,
        reference: IssueReference,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> str:
        payload = self._request_json(
            method="POST",
            url=f"https://api.github.com/repos/{reference.owner}/{reference.repo}/pulls",
            payload={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "draft": True,
            },
        )
        html_url = payload.get("html_url")
        if not isinstance(html_url, str):
            raise GitHubClientError("GitHub pull request response did not include html_url.")
        return html_url

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, object]:
        try:
            completed = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pull_number}"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            completed = None

        if completed is not None and completed.returncode == 0:
            payload = json.loads(completed.stdout)
            if isinstance(payload, dict):
                return payload

        payload = self._request_json(
            method="GET",
            url=f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}",
            payload=None,
        )
        return payload

    def update_pull_request(
        self, owner: str, repo: str, pull_number: int, *, title: str, body: str
    ) -> str:
        gh_url = self._update_pull_request_via_gh(owner, repo, pull_number, title=title, body=body)
        if gh_url is not None:
            return gh_url

        payload = self._request_json(
            method="PATCH",
            url=f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}",
            payload={"title": title, "body": body},
        )
        html_url = payload.get("html_url")
        if not isinstance(html_url, str):
            raise GitHubClientError("GitHub pull request response did not include html_url.")
        return html_url

    def mark_pull_request_ready(self, owner: str, repo: str, pull_number: int) -> None:
        self._request_json(
            method="PATCH",
            url=f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}",
            payload={"draft": False},
        )

    def get_pull_request_head_branch(self, owner: str, repo: str, pull_number: int) -> str | None:
        payload = self.get_pull_request(owner, repo, pull_number)
        head = payload.get("head")
        if not isinstance(head, dict):
            return None
        ref = head.get("ref")
        return ref if isinstance(ref, str) else None

    def get_pull_request_head_sha(self, owner: str, repo: str, pull_number: int) -> str | None:
        try:
            completed = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pull_number}"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            completed = None

        if completed is not None and completed.returncode == 0:
            payload = json.loads(completed.stdout)
            return _extract_pull_head_sha(payload)

        payload = self._request_json(
            method="GET",
            url=f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}",
            payload=None,
        )
        return _extract_pull_head_sha(payload)

    def reopen_issue(self, reference: IssueReference) -> None:
        gh_success = self._reopen_issue_via_gh(reference)
        if gh_success:
            return

        self._request_json(
            method="PATCH",
            url=(
                f"https://api.github.com/repos/{reference.owner}/"
                f"{reference.repo}/issues/{reference.number}"
            ),
            payload={"state": "open"},
        )

    def _reopen_issue_via_gh(self, reference: IssueReference) -> bool:
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
        except OSError:
            return False

        return completed.returncode == 0

    def _update_pull_request_via_gh(
        self, owner: str, repo: str, pull_number: int, *, title: str, body: str
    ) -> str | None:
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
        except OSError:
            return None

        if completed.returncode != 0:
            return None

        payload = json.loads(completed.stdout)
        html_url = payload.get("html_url")
        return html_url if isinstance(html_url, str) else None

    def _request_json(
        self, method: str, url: str, payload: dict[str, object] | None
    ) -> dict[str, object]:
        request = urllib_request.Request(
            url=url,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "precision-squad",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
            data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
        )

        try:
            with urllib_request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubClientError(f"GitHub write failed: HTTP {exc.code}. {detail}") from exc
        except urllib_error.URLError as exc:
            raise GitHubClientError(f"GitHub write failed: {exc.reason}") from exc

    def _list_repo_issues_via_http(self, owner: str, repo: str) -> list[dict[str, object]]:
        request = urllib_request.Request(
            url=f"https://api.github.com/repos/{owner}/{repo}/issues?state=open&per_page=100",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "precision-squad",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        try:
            with urllib_request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubClientError(
                f"GitHub issue list fetch failed for {owner}/{repo}: HTTP {exc.code}. {detail}"
            ) from exc
        except urllib_error.URLError as exc:
            raise GitHubClientError(
                f"GitHub issue list fetch failed for {owner}/{repo}: {exc.reason}"
            ) from exc

        if not isinstance(payload, list):
            raise GitHubClientError(f"GitHub issue list payload for {owner}/{repo} is invalid.")
        return payload


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
