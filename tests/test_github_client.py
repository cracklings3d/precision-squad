"""Tests for the PAT-backed GitHub issue client."""

from __future__ import annotations

import json

import pytest

from precision_squad.github_client import GitHubClientError, GitHubIssueClient, GitHubWriteClient
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
