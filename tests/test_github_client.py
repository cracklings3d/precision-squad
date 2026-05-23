"""Tests for the PAT-backed GitHub issue client."""

from __future__ import annotations

import json

import pytest

from precision_squad.github_client import GitHubClientError, GitHubIssueClient, GitHubWriteClient
from precision_squad.github_transport import GitHubTransportSelectionError
from precision_squad.models import IssueReference


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_from_env_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with pytest.raises(GitHubClientError) as exc_info:
        GitHubIssueClient.from_env()

    assert "GITHUB_TOKEN" in str(exc_info.value)


def test_issue_client_from_env_exposes_transport_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda: object(),
    )

    client = GitHubIssueClient.from_env()

    assert client.transport_resolution is not None


def test_write_client_from_env_exposes_transport_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    resolution = object()
    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda: resolution,
    )

    client = GitHubWriteClient.from_env()

    assert client.transport_resolution is resolution


def test_from_env_propagates_transport_selection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    def fail() -> object:
        raise GitHubTransportSelectionError(
            code="github_transport_cli_unavailable",
            requested_mode="cli",
            summary="gh CLI unavailable",
            decision_reason="cli_required_unavailable",
        )

    monkeypatch.setattr("precision_squad.github_client.resolve_github_transport", fail)

    with pytest.raises(GitHubTransportSelectionError, match="gh CLI unavailable"):
        GitHubWriteClient.from_env()


def test_fetch_issue_returns_normalized_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "title": "[Enhancement] Add --version flag to CLI",
        "body": "## Description\nAdd a version flag.",
        "labels": [{"name": "enhancement"}],
        "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
    }
    comments_payload = [{"body": "Please also handle prior review feedback."}]

    def fake_urlopen(request):
        assert request.full_url.endswith("/repos/cracklings3d/markdown-pdf-renderer/issues/9")
        return _FakeResponse(payload)

    monkeypatch.setattr(
        "precision_squad.github_client.GitHubIssueClient._fetch_issue_via_gh",
        lambda self, reference: None,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubIssueClient._fetch_issue_comments_via_gh",
        lambda self, reference: None,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubIssueClient._fetch_issue_comments_via_http",
        lambda self, reference: comments_payload,
    )
    monkeypatch.setattr("precision_squad.github_client.urllib_request.urlopen", fake_urlopen)

    client = GitHubIssueClient("token")
    issue = client.fetch_issue(IssueReference("cracklings3d", "markdown-pdf-renderer", 9))

    assert issue.reference.number == 9
    assert issue.title == payload["title"]
    assert issue.labels == ("enhancement",)
    assert issue.comments == ("Please also handle prior review feedback.",)


def test_create_issue_uses_http_fallback_when_gh_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._create_issue_via_gh",
        lambda self, owner, repo, *, title, body: None,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._request_json",
        lambda self, method, url, payload: {
            "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/10"
        },
    )

    client = GitHubWriteClient("token")

    url = client.create_issue(
        "cracklings3d",
        "markdown-pdf-renderer",
        title="Docs blocker",
        body="Need deterministic setup docs.",
    )

    assert url == "https://github.com/cracklings3d/markdown-pdf-renderer/issues/10"


def test_find_open_docs_remediation_issue_matches_by_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._list_repo_issues_via_gh",
        lambda self, owner, repo: None,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._list_repo_issues_via_http",
        lambda self, owner, repo: [
            {
                "number": 2,
                "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/2",
                "body": (
                    "<!-- precision-squad:docs-remediation -->\n"
                    "<!-- precision-squad:blocker-findings:[{\"rule_id\":\"docs_setup_command_present\",\"section_key\":\"setup\",\"source_path\":\"readme.md\",\"subject_key\":\"setup-command\"}] -->\n"
                    "<!-- precision-squad:blocker-fingerprint:aaaaaaaaaaaaaaaa -->"
                ),
            },
            {
                "number": 3,
                "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/3",
                "body": (
                    "<!-- precision-squad:docs-remediation -->\n"
                    "<!-- precision-squad:blocker-findings:[{\"rule_id\":\"docs_qa_command_missing\",\"section_key\":\"testing\",\"source_path\":\"readme.md\",\"subject_key\":\"qa-command\"}] -->\n"
                    "<!-- precision-squad:blocker-fingerprint:bbbbbbbbbbbbbbbb -->"
                ),
            },
        ],
    )

    client = GitHubWriteClient("token")

    match = client.find_open_docs_remediation_issue(
        "cracklings3d",
        "markdown-pdf-renderer",
        blocker_fingerprint="bbbbbbbbbbbbbbbb",
        blocker_findings=[
            {
                "rule_id": "docs_qa_command_missing",
                "source_path": "readme.md",
                "section_key": "testing",
                "subject_key": "qa-command",
            }
        ],
    )

    assert match == (3, "https://github.com/cracklings3d/markdown-pdf-renderer/issues/3")


# --- Tests for GitHubWriteClient write methods (close_issue, merge_pull_request, close_pull_request, update_pull_request_branch) ---


class _FakeUrlopenResponse:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self._payload = payload or {}

    def __enter__(self) -> "_FakeUrlopenResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_close_issue_success_via_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """close_issue succeeds when gh CLI returns success."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._close_issue_via_gh",
        lambda self, reference: True,
    )

    client = GitHubWriteClient("token")
    reference = IssueReference("owner", "repo", 5)

    # Should not raise
    client.close_issue(reference)


def test_close_issue_fallback_to_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """close_issue falls back to HTTP when gh CLI returns False."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._close_issue_via_gh",
        lambda self, reference: False,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._request_json",
        lambda self, method, url, payload: {},
    )

    client = GitHubWriteClient("token")
    reference = IssueReference("owner", "repo", 5)

    # Should not raise
    client.close_issue(reference)


def test_close_issue_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """close_issue raises GitHubClientError on HTTP failure."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._close_issue_via_gh",
        lambda self, reference: False,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._request_json",
        lambda self, method, url, payload: (_ for _ in ()).throw(
            GitHubClientError("GitHub write failed: HTTP 403. Forbidden")
        ),
    )

    client = GitHubWriteClient("token")
    reference = IssueReference("owner", "repo", 5)

    with pytest.raises(GitHubClientError, match="HTTP 403"):
        client.close_issue(reference)


def test_merge_pull_request_success_via_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """merge_pull_request succeeds when gh CLI returns True."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._merge_pull_request_via_gh",
        lambda self, owner, repo, pull_number: True,
    )

    client = GitHubWriteClient("token")

    # Should not raise
    client.merge_pull_request("owner", "repo", 5)


def test_merge_pull_request_fallback_to_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """merge_pull_request falls back to HTTP when gh CLI returns False."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._merge_pull_request_via_gh",
        lambda self, owner, repo, pull_number: False,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._request_json",
        lambda self, method, url, payload: {},
    )

    client = GitHubWriteClient("token")

    # Should not raise
    client.merge_pull_request("owner", "repo", 5)


def test_merge_pull_request_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """merge_pull_request raises GitHubClientError on HTTP failure."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._merge_pull_request_via_gh",
        lambda self, owner, repo, pull_number: False,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._request_json",
        lambda self, method, url, payload: (_ for _ in ()).throw(
            GitHubClientError("GitHub write failed: HTTP 410. Resource not found")
        ),
    )

    client = GitHubWriteClient("token")

    with pytest.raises(GitHubClientError, match="HTTP 410"):
        client.merge_pull_request("owner", "repo", 5)


def test_close_pull_request_success_via_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """close_pull_request succeeds when gh CLI returns True."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._close_pull_request_via_gh",
        lambda self, owner, repo, pull_number: True,
    )

    client = GitHubWriteClient("token")

    # Should not raise
    client.close_pull_request("owner", "repo", 5)


def test_close_pull_request_fallback_to_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """close_pull_request falls back to HTTP when gh CLI returns False."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._close_pull_request_via_gh",
        lambda self, owner, repo, pull_number: False,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._request_json",
        lambda self, method, url, payload: {},
    )

    client = GitHubWriteClient("token")

    # Should not raise
    client.close_pull_request("owner", "repo", 5)


def test_close_pull_request_http_404_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """close_pull_request raises GitHubClientError on HTTP 404 failure (not 405 which is swallowed)."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._close_pull_request_via_gh",
        lambda self, owner, repo, pull_number: False,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._request_json",
        lambda self, method, url, payload: (_ for _ in ()).throw(
            GitHubClientError("GitHub write failed: HTTP 404. Not found")
        ),
    )

    client = GitHubWriteClient("token")

    with pytest.raises(GitHubClientError, match="HTTP 404"):
        client.close_pull_request("owner", "repo", 5)


def test_update_pull_request_branch_success_via_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """update_pull_request_branch succeeds when gh CLI returns True."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._update_pull_request_branch_via_gh",
        lambda self, owner, repo, pull_number: True,
    )

    client = GitHubWriteClient("token")

    # Should not raise
    client.update_pull_request_branch("owner", "repo", 5)


def test_update_pull_request_branch_fallback_to_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """update_pull_request_branch falls back to HTTP when gh CLI returns False."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._update_pull_request_branch_via_gh",
        lambda self, owner, repo, pull_number: False,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._request_json",
        lambda self, method, url, payload: {},
    )

    client = GitHubWriteClient("token")

    # Should not raise
    client.update_pull_request_branch("owner", "repo", 5)


def test_update_pull_request_branch_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """update_pull_request_branch raises GitHubClientError on HTTP failure."""
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._update_pull_request_branch_via_gh",
        lambda self, owner, repo, pull_number: False,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubWriteClient._request_json",
        lambda self, method, url, payload: (_ for _ in ()).throw(
            GitHubClientError("GitHub write failed: HTTP 422. Validation failed")
        ),
    )

    client = GitHubWriteClient("token")

    with pytest.raises(GitHubClientError, match="HTTP 422"):
        client.update_pull_request_branch("owner", "repo", 5)
