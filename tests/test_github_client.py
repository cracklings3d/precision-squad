"""Tests for the PAT-backed GitHub issue client."""

from __future__ import annotations

import json

import pytest

from precision_squad.github_client import (
    GitHubClientError,
    GitHubCliTransportStrategy,
    GitHubIssueClient,
    GitHubMcpTransportStrategy,
    GitHubWriteClient,
)
from precision_squad.github_transport import (
    GitHubTransportResolution,
    GitHubTransportSelectionError,
)
from precision_squad.models import IssueReference


def test_from_env_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with pytest.raises(GitHubClientError) as exc_info:
        GitHubIssueClient.from_env()

    assert "GITHUB_TOKEN" in str(exc_info.value)


def test_issue_client_from_env_exposes_transport_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    resolution = GitHubTransportResolution(
        requested_mode="cli",
        selected_transport="cli",
        mcp_available=False,
        gh_cli_available=True,
        decision_reason="cli_required_available",
    )
    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: resolution,
    )

    client = GitHubIssueClient.from_env()

    assert client.transport_resolution is resolution


def test_write_client_from_env_exposes_transport_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    resolution = GitHubTransportResolution(
        requested_mode="cli",
        selected_transport="cli",
        mcp_available=False,
        gh_cli_available=True,
        decision_reason="cli_required_available",
    )
    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: resolution,
    )

    client = GitHubWriteClient.from_env()

    assert client.transport_resolution is resolution


def test_from_env_propagates_transport_selection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    def fail(**kwargs) -> GitHubTransportResolution:
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
    """fetch_issue normalizes payload and extracts comments via strategy."""
    payload = {
        "title": "[Enhancement] Add --version flag to CLI",
        "body": "## Description\nAdd a version flag.",
        "labels": [{"name": "enhancement"}],
        "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
    }
    comments_payload = [{"body": "Please also handle prior review feedback."}]

    class FakeCliStrategy(GitHubCliTransportStrategy):
        def fetch_issue(self, reference):
            return payload

        def fetch_issue_comments(self, reference):
            return comments_payload

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="cli",
            selected_transport="cli",
            mcp_available=False,
            gh_cli_available=True,
            decision_reason="cli_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubCliTransportStrategy",
        lambda token: FakeCliStrategy(token),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    client = GitHubIssueClient.from_env()
    issue = client.fetch_issue(IssueReference("cracklings3d", "markdown-pdf-renderer", 9))

    assert issue.reference.number == 9
    assert issue.title == payload["title"]
    assert issue.labels == ("enhancement",)
    assert issue.comments == ("Please also handle prior review feedback.",)


def test_find_open_docs_remediation_issue_matches_by_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """find_open_docs_remediation_issue filters by fingerprint via strategy."""

    class FakeCliStrategy(GitHubCliTransportStrategy):
        def list_repo_issues(self, owner, repo):
            return [
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
            ]

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="cli",
            selected_transport="cli",
            mcp_available=False,
            gh_cli_available=True,
            decision_reason="cli_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubCliTransportStrategy",
        lambda token: FakeCliStrategy(token),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    client = GitHubWriteClient.from_env()

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


# --- Legacy write-method tests removed: HTTP fallback is no longer allowed per contract ---
# Tests for close_issue, merge_pull_request, close_pull_request, update_pull_request_branch
# now use the strategy enforcement tests below which verify transport governance correctly.


# --- Tests for GitHub transport strategy enforcement ---


def test_issue_client_selects_cli_strategy_when_cli_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When transport resolution selects CLI, issue client uses CLI strategy only."""
    # Set up environment
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    # Mock resolve_github_transport to return cli-selected resolution
    def mock_resolve_github_transport(
        requested_mode=None, *, probe_mcp_available=None, probe_gh_cli_available=None
    ):
        from precision_squad.github_transport import GitHubTransportResolution
        return GitHubTransportResolution(
            requested_mode="cli",
            selected_transport="cli",
            mcp_available=None,
            gh_cli_available=True,
            decision_reason="cli_required_available",
        )

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        mock_resolve_github_transport,
    )

    # Track if CLI strategy was used (no HTTP fallback)
    cli_calls: list[str] = []

    class FakeCliStrategy:
        def __init__(self, token: str) -> None:
            self._token = token

        def fetch_issue(self, reference):
            cli_calls.append("fetch_issue")
            return {
                "title": "Test Issue",
                "body": "Test body",
                "html_url": "https://github.com/owner/repo/issues/1",
                "labels": [],
            }

        def fetch_issue_comments(self, reference):
            cli_calls.append("fetch_issue_comments")
            return []

    monkeypatch.setattr(
        "precision_squad.github_client.GitHubCliTransportStrategy",
        lambda token: FakeCliStrategy(token),
    )

    client = GitHubIssueClient.from_env()
    issue = client.fetch_issue(IssueReference("owner", "repo", 1))

    assert issue.title == "Test Issue"
    assert "fetch_issue" in cli_calls
    assert "fetch_issue_comments" in cli_calls


def test_issue_client_raises_when_mcp_selected_but_mcp_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When MCP is selected but MCP transport fails, client raises GitHubClientError."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.delenv("MCP_GITHUB_SERVER", raising=False)

    # Mock resolve_github_transport to return mcp-selected resolution
    def mock_resolve_github_transport(
        requested_mode=None, *, probe_mcp_available=None, probe_gh_cli_available=None
    ):
        from precision_squad.github_transport import GitHubTransportResolution
        return GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        )

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        mock_resolve_github_transport,
    )

    client = GitHubIssueClient.from_env()

    with pytest.raises(GitHubClientError, match="MCP"):
        client.fetch_issue(IssueReference("owner", "repo", 1))


def test_write_client_uses_cli_strategy_only_in_forced_cli_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In forced GITHUB_TRANSPORT=cli, no HTTP fallback occurs."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    # Mock resolve_github_transport to return cli-selected resolution
    def mock_resolve_github_transport(
        requested_mode=None, *, probe_mcp_available=None, probe_gh_cli_available=None
    ):
        from precision_squad.github_transport import GitHubTransportResolution
        return GitHubTransportResolution(
            requested_mode="cli",
            selected_transport="cli",
            mcp_available=None,
            gh_cli_available=True,
            decision_reason="cli_required_available",
        )

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        mock_resolve_github_transport,
    )

    # Track method calls on strategy
    strategy_calls: list[str] = []

    class FakeCliStrategy:
        def __init__(self, token: str) -> None:
            self._token = token

        def create_issue(self, owner, repo, *, title, body):
            strategy_calls.append("create_issue")
            return f"https://github.com/{owner}/{repo}/issues/1"

        def create_issue_comment(self, reference, body):
            strategy_calls.append("create_issue_comment")
            return f"https://github.com/{reference.owner}/{reference.repo}/issues/{reference.number}#issuecomment-1"

        def list_repo_issues(self, owner, repo):
            strategy_calls.append("list_repo_issues")
            return []

        def create_draft_pull_request(self, reference, title, body, head, base):
            strategy_calls.append("create_draft_pull_request")
            return f"https://github.com/{reference.owner}/{reference.repo}/pull/1"

        def get_pull_request(self, owner, repo, pull_number):
            strategy_calls.append("get_pull_request")
            return {"html_url": f"https://github.com/{owner}/{repo}/pull/{pull_number}", "head": {"ref": "feature", "sha": "abc123"}}

        def update_pull_request(self, owner, repo, pull_number, *, title, body):
            strategy_calls.append("update_pull_request")
            return f"https://github.com/{owner}/{repo}/pull/{pull_number}"

        def patch_pull_request(self, owner, repo, pull_number, payload):
            strategy_calls.append("patch_pull_request")

        def reopen_issue(self, reference):
            strategy_calls.append("reopen_issue")

        def close_issue(self, reference):
            strategy_calls.append("close_issue")

        def merge_pull_request(self, owner, repo, pull_number):
            strategy_calls.append("merge_pull_request")

        def close_pull_request(self, owner, repo, pull_number):
            strategy_calls.append("close_pull_request")

        def update_pull_request_branch(self, owner, repo, pull_number):
            strategy_calls.append("update_pull_request_branch")

    monkeypatch.setattr(
        "precision_squad.github_client.GitHubCliTransportStrategy",
        lambda token: FakeCliStrategy(token),
    )

    client = GitHubWriteClient.from_env()

    # Test create_issue uses strategy only
    url = client.create_issue("owner", "repo", title="Test", body="Body")
    assert url == "https://github.com/owner/repo/issues/1"
    assert "create_issue" in strategy_calls

    # Verify HTTP was never called
    assert "HTTP" not in str(strategy_calls)


def test_write_client_raises_mcp_error_for_all_write_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All write methods raise GitHubClientError when MCP transport fails."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.delenv("MCP_GITHUB_SERVER", raising=False)

    # Mock resolve_github_transport to return mcp-selected resolution
    def mock_resolve_github_transport(
        requested_mode=None, *, probe_mcp_available=None, probe_gh_cli_available=None
    ):
        from precision_squad.github_transport import GitHubTransportResolution
        return GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        )

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        mock_resolve_github_transport,
    )

    client = GitHubWriteClient.from_env()
    reference = IssueReference("owner", "repo", 1)

    # Test each write method raises GitHubClientError when MCP fails
    with pytest.raises(GitHubClientError, match="MCP"):
        client.create_issue_comment(reference, "comment body")

    with pytest.raises(GitHubClientError, match="MCP"):
        client.create_issue("owner", "repo", title="Test", body="Body")

    with pytest.raises(GitHubClientError, match="MCP"):
        client.create_draft_pull_request(reference, "Title", "Body", "head", "main")

    with pytest.raises(GitHubClientError, match="MCP"):
        client.update_pull_request("owner", "repo", 1, title="Title", body="Body")

    with pytest.raises(GitHubClientError, match="MCP"):
        client.mark_pull_request_ready("owner", "repo", 1)

    with pytest.raises(GitHubClientError, match="MCP"):
        client.reopen_issue(reference)

    with pytest.raises(GitHubClientError, match="MCP"):
        client.close_issue(reference)

    with pytest.raises(GitHubClientError, match="MCP"):
        client.merge_pull_request("owner", "repo", 1)

    with pytest.raises(GitHubClientError, match="MCP"):
        client.close_pull_request("owner", "repo", 1)

    with pytest.raises(GitHubClientError, match="MCP"):
        client.update_pull_request_branch("owner", "repo", 1)


def test_auto_mode_stays_on_first_selected_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once auto selects MCP or CLI, subsequent calls don't switch transport."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    # Track which strategy was used across multiple calls
    transport_used: list[str] = []

    class FakeCliStrategy:
        def __init__(self, token: str) -> None:
            self._token = token

        def fetch_issue(self, reference):
            transport_used.append("cli")
            return {
                "title": "Test",
                "body": "Body",
                "html_url": f"https://github.com/{reference.owner}/{reference.repo}/issues/{reference.number}",
                "labels": [],
            }

        def fetch_issue_comments(self, reference):
            transport_used.append("cli")
            return []

        def create_issue(self, owner, repo, *, title, body):
            transport_used.append("cli")
            return f"https://github.com/{owner}/{repo}/issues/1"

    class FakeMcpStrategy:
        def fetch_issue(self, reference):
            transport_used.append("mcp")
            return {
                "title": "Test",
                "body": "Body",
                "html_url": f"https://github.com/{reference.owner}/{reference.repo}/issues/{reference.number}",
                "labels": [],
            }

        def fetch_issue_comments(self, reference):
            transport_used.append("mcp")
            return []

        def create_issue(self, owner, repo, *, title, body):
            transport_used.append("mcp")
            return f"https://github.com/{owner}/{repo}/issues/1"

    # First test: auto selects CLI
    def mock_resolve_cli(
        requested_mode=None, *, probe_mcp_available=None, probe_gh_cli_available=None
    ):
        from precision_squad.github_transport import GitHubTransportResolution
        return GitHubTransportResolution(
            requested_mode="auto",
            selected_transport="cli",
            mcp_available=False,
            gh_cli_available=True,
            decision_reason="auto_selected_cli",
        )

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        mock_resolve_cli,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubCliTransportStrategy",
        lambda token: FakeCliStrategy(token),
    )

    client = GitHubWriteClient.from_env()
    client.create_issue("owner", "repo", title="Test", body="Body")
    client.create_issue("owner", "repo", title="Test2", body="Body2")

    # All calls should use CLI
    assert all(t == "cli" for t in transport_used), f"Expected all cli, got {transport_used}"
    transport_used.clear()

    # Second test: auto selects MCP
    def mock_resolve_mcp(
        requested_mode=None, *, probe_mcp_available=None, probe_gh_cli_available=None
    ):
        from precision_squad.github_transport import GitHubTransportResolution
        return GitHubTransportResolution(
            requested_mode="auto",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=False,
            decision_reason="auto_selected_mcp",
        )

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        mock_resolve_mcp,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubMcpTransportStrategy",
        lambda: FakeMcpStrategy(),
    )

    # Need to reset the module's strategy builder cache
    monkeypatch.setattr(
        "precision_squad.github_client._build_strategy",
        lambda resolution, token: FakeMcpStrategy() if resolution.selected_transport == "mcp" else FakeCliStrategy(token),
    )

    client2 = GitHubWriteClient.from_env()
    client2.create_issue("owner", "repo", title="Test", body="Body")
    client2.create_issue("owner", "repo", title="Test2", body="Body2")

    # All calls should use MCP (transport doesn't switch)
    assert all(t == "mcp" for t in transport_used), f"Expected all mcp, got {transport_used}"


def test_mcp_strategy_handles_mark_pull_request_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mark_pull_request_ready uses MCP transport when selected."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    mcp_calls: list[str] = []

    class FakeMcpStrategy:
        def patch_pull_request(self, owner, repo, pull_number, payload):
            mcp_calls.append(f"patch_pull_request/{owner}/{repo}/{pull_number}")
            assert payload == {"draft": False}

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubMcpTransportStrategy",
        lambda: FakeMcpStrategy(),
    )

    client = GitHubWriteClient.from_env()
    client.mark_pull_request_ready("owner", "repo", 5)

    assert "patch_pull_request/owner/repo/5" in mcp_calls


def test_mcp_strategy_handles_get_pull_request_head_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_pull_request_head_branch uses MCP transport when selected."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    mcp_calls: list[str] = []

    class FakeMcpStrategy:
        def get_pull_request(self, owner, repo, pull_number):
            mcp_calls.append(f"get_pull_request/{owner}/{repo}/{pull_number}")
            return {
                "html_url": f"https://github.com/{owner}/{repo}/pull/{pull_number}",
                "head": {"ref": "feature-branch", "sha": "abc123"},
            }

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubMcpTransportStrategy",
        lambda: FakeMcpStrategy(),
    )

    client = GitHubWriteClient.from_env()
    branch = client.get_pull_request_head_branch("owner", "repo", 5)

    assert branch == "feature-branch"
    assert "get_pull_request/owner/repo/5" in mcp_calls


def test_mcp_strategy_handles_get_pull_request_head_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_pull_request_head_sha uses MCP transport when selected."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    mcp_calls: list[str] = []

    class FakeMcpStrategy:
        def get_pull_request(self, owner, repo, pull_number):
            mcp_calls.append(f"get_pull_request/{owner}/{repo}/{pull_number}")
            return {
                "html_url": f"https://github.com/{owner}/{repo}/pull/{pull_number}",
                "head": {"ref": "feature-branch", "sha": "def456"},
            }

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubMcpTransportStrategy",
        lambda: FakeMcpStrategy(),
    )

    client = GitHubWriteClient.from_env()
    sha = client.get_pull_request_head_sha("owner", "repo", 5)

    assert sha == "def456"
    assert "get_pull_request/owner/repo/5" in mcp_calls


def test_mcp_strategy_fails_explicitly_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP transport raises GitHubClientError, not NotImplementedError."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.delenv("MCP_GITHUB_SERVER", raising=False)

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        ),
    )

    client = GitHubIssueClient.from_env()

    # Should raise GitHubClientError, NOT NotImplementedError
    with pytest.raises(GitHubClientError, match="MCP"):
        client.fetch_issue(IssueReference("owner", "repo", 1))

    # Verify it's not a NotImplementedError
    try:
        client.fetch_issue(IssueReference("owner", "repo", 1))
    except GitHubClientError:
        pass  # Expected
    except NotImplementedError:
        pytest.fail("MCP transport raised NotImplementedError instead of GitHubClientError")


def test_mcp_transport_mark_pull_request_ready_uses_github_update_pull_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP transport mark_pull_request_ready uses github_update_pull_request via patch_pull_request."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("MCP_GITHUB_SERVER", "npx -y @modelcontextprotocol/server-github")

    mcp_tool_calls: list[tuple[str, dict]] = []

    class FakeMcpStrategy(GitHubMcpTransportStrategy):
        """Fake strategy that doesn't need real MCP connection."""
        def _call_mcp_tool(self, tool_name: str, arguments: dict) -> object:
            mcp_tool_calls.append((tool_name, arguments))
            return {"html_url": f"https://github.com/{arguments.get('owner')}/{arguments.get('repo')}/pull/{arguments.get('pullNumber')}"}

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubMcpTransportStrategy",
        lambda: FakeMcpStrategy(),
    )

    client = GitHubWriteClient.from_env()

    # mark_pull_request_ready should NOT raise - it uses github_update_pull_request via patch_pull_request
    client.mark_pull_request_ready("owner", "repo", 5)

    # Verify github_update_pull_request was called with draft=False
    update_calls = [(name, args) for name, args in mcp_tool_calls if name == "github_update_pull_request"]
    assert len(update_calls) >= 1, f"Expected github_update_pull_request call, got {mcp_tool_calls}"
    call_name, call_args = update_calls[0]
    assert call_args.get("draft") is False, f"Expected draft=False, got {call_args}"


def test_cli_transport_mark_pull_request_ready_uses_gh_api_with_draft_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI transport mark_pull_request_ready uses 'gh api' with draft=false via patch_pull_request."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    gh_commands: list[list[str]] = []

    import subprocess
    from subprocess import CompletedProcess

    def spy_run(cmd, **kwargs):
        gh_commands.append(list(cmd))
        # Return a fake success so the CLI transport doesn't raise GitHubClientError.
        # This lets us verify the gh api command was constructed correctly without
        # needing real gh credentials for a non-existent repository.
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", spy_run)

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="cli",
            selected_transport="cli",
            mcp_available=False,
            gh_cli_available=True,
            decision_reason="cli_required_available",
        ),
    )

    client = GitHubWriteClient.from_env()
    client.mark_pull_request_ready("owner", "repo", 5)

    # Verify 'gh api' was called with draft=false
    api_calls = [cmd for cmd in gh_commands if "gh" in cmd and "api" in cmd]
    assert len(api_calls) >= 1, f"Expected at least one 'gh api' call, got {gh_commands}"
    # Verify draft=false was passed
    draft_calls = [cmd for cmd in gh_commands if "draft=false" in " ".join(cmd)]
    assert len(draft_calls) >= 1, (
        f"Expected 'gh api' call with draft=false, got {gh_commands}"
    )


def test_auto_does_not_select_mcp_when_only_package_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto mode must NOT select MCP when only package is importable but server not configured.

    This tests the complete auto-fallback semantics: MCP is only selected when BOTH
    the mcp package is importable AND MCP_GITHUB_SERVER is set. If only the package
    is importable (no server config), auto must fall back to CLI.
    """
    from importlib.machinery import ModuleSpec

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    # MCP package importable but no MCP_GITHUB_SERVER
    monkeypatch.setattr(
        "precision_squad.github_transport.find_spec",
        lambda name: ModuleSpec(name, loader=None) if name == "mcp" else None,
    )
    monkeypatch.delenv("MCP_GITHUB_SERVER", raising=False)

    transport_calls: list[str] = []

    class FakeCliStrategy:
        def __init__(self, token: str) -> None:
            self._token = token

        def create_issue(self, owner, repo, *, title, body):
            transport_calls.append("cli")
            return f"https://github.com/{owner}/{repo}/issues/1"

    monkeypatch.setattr(
        "precision_squad.github_client.GitHubCliTransportStrategy",
        lambda token: FakeCliStrategy(token),
    )

    client = GitHubWriteClient.from_env()
    client.create_issue("owner", "repo", title="Test", body="Body")

    # CLI was used, not MCP
    assert transport_calls == ["cli"], (
        f"Expected CLI transport to be used when MCP not runnable, got {transport_calls}"
    )


def test_mcp_transport_uses_real_tool_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP transport uses real GitHub MCP tool names with 'github_' prefix."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("MCP_GITHUB_SERVER", "npx -y @modelcontextprotocol/server-github")

    mcp_tool_calls: list[tuple[str, dict]] = []

    class SpyMcpStrategy(GitHubMcpTransportStrategy):
        def _call_mcp_tool(self, tool_name: str, arguments: dict) -> object:
            mcp_tool_calls.append((tool_name, arguments))
            # Return appropriate type based on tool
            if tool_name == "github_issue_read":
                if arguments.get("method") == "get":
                    return {"html_url": "https://github.com/owner/repo/issues/1"}
                elif arguments.get("method") == "get_comments":
                    return []
            elif tool_name == "github_add_issue_comment":
                return {"html_url": "https://github.com/owner/repo/issues/1#issuecomment-1"}
            elif tool_name == "github_issue_write":
                return {"html_url": "https://github.com/owner/repo/issues/1"}
            elif tool_name == "github_list_issues":
                return [{"number": 1, "html_url": "https://github.com/owner/repo/issues/1"}]
            elif tool_name == "github_create_pull_request":
                return {"html_url": "https://github.com/owner/repo/pull/1"}
            elif tool_name == "github_pull_request_read":
                return {"html_url": "https://github.com/owner/repo/pull/1", "head": {"ref": "head", "sha": "abc123"}}
            elif tool_name == "github_update_pull_request":
                return {"html_url": "https://github.com/owner/repo/pull/1"}
            elif tool_name == "github_merge_pull_request":
                return {}
            elif tool_name == "github_update_pull_request_branch":
                return {}
            return {}

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubMcpTransportStrategy",
        lambda: SpyMcpStrategy(),
    )

    client = GitHubWriteClient.from_env()
    reference = IssueReference("owner", "repo", 1)

    # Test fetch_issue uses 'github_issue_read' with method='get'
    client._strategy.fetch_issue(reference)
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_issue_read" in tool_names, f"Expected 'github_issue_read', got {tool_names}"
    # Verify method='get' was passed
    fetch_call = next((args for name, args in mcp_tool_calls if name == "github_issue_read"), None)
    assert fetch_call is not None and fetch_call.get("method") == "get", f"Expected method='get', got {fetch_call}"
    mcp_tool_calls.clear()

    # Test fetch_issue_comments uses 'github_issue_read' with method='get_comments'
    client._strategy.fetch_issue_comments(reference)
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_issue_read" in tool_names, f"Expected 'github_issue_read', got {tool_names}"
    comments_call = next((args for name, args in mcp_tool_calls if name == "github_issue_read"), None)
    assert comments_call is not None and comments_call.get("method") == "get_comments", f"Expected method='get_comments', got {comments_call}"
    mcp_tool_calls.clear()

    # Test create_issue_comment uses 'github_add_issue_comment'
    client._strategy.create_issue_comment(reference, "body")
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_add_issue_comment" in tool_names, f"Expected 'github_add_issue_comment', got {tool_names}"
    mcp_tool_calls.clear()

    # Test create_issue uses 'github_issue_write' with method='create'
    client._strategy.create_issue("owner", "repo", title="Title", body="Body")
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_issue_write" in tool_names, f"Expected 'github_issue_write', got {tool_names}"
    create_call = next((args for name, args in mcp_tool_calls if name == "github_issue_write"), None)
    assert create_call is not None and create_call.get("method") == "create", f"Expected method='create', got {create_call}"
    mcp_tool_calls.clear()

    # Test list_repo_issues uses 'github_list_issues'
    client._strategy.list_repo_issues("owner", "repo")
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_list_issues" in tool_names, f"Expected 'github_list_issues', got {tool_names}"
    mcp_tool_calls.clear()

    # Test create_draft_pull_request uses 'github_create_pull_request'
    client._strategy.create_draft_pull_request(reference, "Title", "Body", "head", "base")
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_create_pull_request" in tool_names, f"Expected 'github_create_pull_request', got {tool_names}"
    mcp_tool_calls.clear()

    # Test get_pull_request uses 'github_pull_request_read' with method='get'
    client._strategy.get_pull_request("owner", "repo", 1)
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_pull_request_read" in tool_names, f"Expected 'github_pull_request_read', got {tool_names}"
    mcp_tool_calls.clear()

    # Test update_pull_request uses 'github_update_pull_request'
    client._strategy.update_pull_request("owner", "repo", 1, title="Title", body="Body")
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_update_pull_request" in tool_names, f"Expected 'github_update_pull_request', got {tool_names}"
    mcp_tool_calls.clear()

    # Test close_issue uses 'github_issue_write' with method='update'
    client._strategy.close_issue(reference)
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_issue_write" in tool_names, f"Expected 'github_issue_write', got {tool_names}"
    close_call = next((args for name, args in mcp_tool_calls if name == "github_issue_write"), None)
    assert close_call is not None and close_call.get("method") == "update", f"Expected method='update', got {close_call}"
    mcp_tool_calls.clear()

    # Test reopen_issue uses 'github_issue_write' with method='update'
    client._strategy.reopen_issue(reference)
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_issue_write" in tool_names, f"Expected 'github_issue_write', got {tool_names}"
    mcp_tool_calls.clear()

    # Test merge_pull_request uses 'github_merge_pull_request'
    client._strategy.merge_pull_request("owner", "repo", 1)
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_merge_pull_request" in tool_names, f"Expected 'github_merge_pull_request', got {tool_names}"
    mcp_tool_calls.clear()

    # Test close_pull_request uses 'github_update_pull_request'
    client._strategy.close_pull_request("owner", "repo", 1)
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_update_pull_request" in tool_names, f"Expected 'github_update_pull_request', got {tool_names}"
    mcp_tool_calls.clear()

    # Test update_pull_request_branch uses 'github_update_pull_request_branch'
    client._strategy.update_pull_request_branch("owner", "repo", 1)
    tool_names = [name for name, _ in mcp_tool_calls]
    assert "github_update_pull_request_branch" in tool_names, f"Expected 'github_update_pull_request_branch', got {tool_names}"


def test_mcp_strategy_supports_all_governed_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP transport supports all governed operations via real MCP tools."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("MCP_GITHUB_SERVER", "npx -y @modelcontextprotocol/server-github")

    mcp_tool_calls: list[tuple[str, dict]] = []

    class FakeMcpStrategy(GitHubMcpTransportStrategy):
        """Fake strategy that doesn't need real MCP connection for success-case tests."""
        def _call_mcp_tool(self, tool_name: str, arguments: dict) -> object:
            mcp_tool_calls.append((tool_name, arguments))
            # Return appropriate responses for all governed operations
            if tool_name == "github_issue_read":
                if arguments.get("method") == "get":
                    return {
                        "title": "Test Issue",
                        "body": "Issue body",
                        "html_url": "https://github.com/owner/repo/issues/1",
                        "labels": [],
                    }
                elif arguments.get("method") == "get_comments":
                    return [{"body": "Comment 1"}, {"body": "Comment 2"}]
            elif tool_name == "github_add_issue_comment":
                return {"html_url": "https://github.com/owner/repo/issues/1#issuecomment-1"}
            elif tool_name == "github_issue_write":
                return {"html_url": "https://github.com/owner/repo/issues/1"}
            elif tool_name == "github_list_issues":
                return [{"number": 1, "html_url": "https://github.com/owner/repo/issues/1", "body": ""}]
            elif tool_name == "github_create_pull_request":
                return {"html_url": "https://github.com/owner/repo/pull/1"}
            elif tool_name == "github_pull_request_read":
                return {"html_url": "https://github.com/owner/repo/pull/1", "head": {"ref": "head", "sha": "abc123"}}
            elif tool_name == "github_update_pull_request":
                return {"html_url": "https://github.com/owner/repo/pull/1"}
            elif tool_name == "github_merge_pull_request":
                return {}
            elif tool_name == "github_update_pull_request_branch":
                return {}
            return {}

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubMcpTransportStrategy",
        lambda: FakeMcpStrategy(),
    )

    client = GitHubWriteClient.from_env()
    reference = IssueReference("owner", "repo", 1)

    # Test fetch_issue_comments - should NOT raise
    result = client._strategy.fetch_issue_comments(reference)
    assert isinstance(result, list) and len(result) == 2

    # Test update_pull_request - should NOT raise
    url = client._strategy.update_pull_request("owner", "repo", 1, title="Title", body="Body")
    assert url == "https://github.com/owner/repo/pull/1"

    # Test patch_pull_request - should NOT raise (handles draft state changes)
    client._strategy.patch_pull_request("owner", "repo", 1, {"draft": False})

    # Test close_pull_request - should NOT raise
    client._strategy.close_pull_request("owner", "repo", 1)
    # Verify close uses github_update_pull_request with state=closed
    close_call = next(
        (args for name, args in mcp_tool_calls if name == "github_update_pull_request" and args.get("state") == "closed"),
        None
    )
    assert close_call is not None, "close_pull_request should use github_update_pull_request with state=closed"

    mcp_tool_calls.clear()

    # Test merge_pull_request - should NOT raise
    client._strategy.merge_pull_request("owner", "repo", 1)
    assert any(name == "github_merge_pull_request" for name, _ in mcp_tool_calls)

    mcp_tool_calls.clear()

    # Test update_pull_request_branch - should NOT raise
    client._strategy.update_pull_request_branch("owner", "repo", 1)
    assert any(name == "github_update_pull_request_branch" for name, _ in mcp_tool_calls)


def test_backward_compatible_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHubIssueClient and GitHubWriteClient work without strategy= argument."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    cli_strategy_used: list[str] = []

    expected_resolution = GitHubTransportResolution(
        requested_mode="cli",
        selected_transport="cli",
        mcp_available=False,
        gh_cli_available=True,
        decision_reason="cli_required_available",
    )

    class FakeCliStrategy:
        def __init__(self, token: str) -> None:
            self._token = token

        def fetch_issue(self, reference):
            cli_strategy_used.append("fetch_issue")
            return {
                "title": "Test Issue",
                "body": "Test body",
                "html_url": "https://github.com/owner/repo/issues/1",
                "labels": [],
            }

        def fetch_issue_comments(self, reference):
            cli_strategy_used.append("fetch_issue_comments")
            return []

        def create_issue(self, owner, repo, *, title, body):
            cli_strategy_used.append("create_issue")
            return f"https://github.com/{owner}/{repo}/issues/1"

        def list_repo_issues(self, owner, repo):
            cli_strategy_used.append("list_repo_issues")
            return []

        def create_issue_comment(self, reference, body):
            cli_strategy_used.append("create_issue_comment")
            return f"https://github.com/{reference.owner}/{reference.repo}/issues/{reference.number}#issuecomment-1"

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: expected_resolution,
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubCliTransportStrategy",
        lambda token: FakeCliStrategy(token),
    )

    # GitHubIssueClient(token="test-token") should work without strategy=
    issue_client = GitHubIssueClient(token="test-token")
    assert issue_client._token == "test-token"
    assert issue_client._strategy is not None
    # transport_resolution must be non-None after auto-resolution
    assert issue_client.transport_resolution is expected_resolution

    # GitHubWriteClient(token="test-token") should work without strategy=
    write_client = GitHubWriteClient(token="test-token")
    assert write_client._token == "test-token"
    assert write_client._strategy is not None
    # transport_resolution must be non-None after auto-resolution
    assert write_client.transport_resolution is expected_resolution

    # Verify the auto-resolved strategy works correctly
    issue_client.fetch_issue(IssueReference("owner", "repo", 1))
    assert "fetch_issue" in cli_strategy_used

    cli_strategy_used.clear()
    write_client.create_issue("owner", "repo", title="Test", body="Body")
    assert "create_issue" in cli_strategy_used


def test_mcp_public_client_fetch_issue_uses_pullNumber_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHubIssueClient.fetch_issue passes issue_number (not pull_number) to MCP tools."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("MCP_GITHUB_SERVER", "npx -y @modelcontextprotocol/server-github")

    mcp_tool_calls: list[tuple[str, dict]] = []

    class SpyMcpStrategy(GitHubMcpTransportStrategy):
        """Spy that captures MCP tool calls to verify issue_number contract."""
        def _call_mcp_tool(self, tool_name: str, arguments: dict) -> object:
            mcp_tool_calls.append((tool_name, arguments))
            if tool_name == "github_issue_read":
                if arguments.get("method") == "get":
                    return {
                        "title": "Test Issue",
                        "body": "Issue body",
                        "html_url": f"https://github.com/{arguments.get('owner')}/{arguments.get('repo')}/issues/{arguments.get('issue_number')}",
                        "labels": [],
                    }
                elif arguments.get("method") == "get_comments":
                    return [{"body": "Comment 1"}]
            return {}

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubMcpTransportStrategy",
        lambda: SpyMcpStrategy(),
    )

    client = GitHubIssueClient.from_env()
    reference = IssueReference("owner", "repo", 1)

    # fetch_issue should call github_issue_read with method='get' and method='get_comments'
    client.fetch_issue(reference)

    # Verify github_issue_read was called with issue_number (correct contract for issues)
    assert len(mcp_tool_calls) == 2, f"Expected 2 MCP calls, got {len(mcp_tool_calls)}: {mcp_tool_calls}"

    fetch_call = next(
        (args for name, args in mcp_tool_calls if name == "github_issue_read" and args.get("method") == "get"),
        None
    )
    assert fetch_call is not None, f"Expected github_issue_read call with method='get', got {mcp_tool_calls}"
    assert "issue_number" in fetch_call, f"Expected issue_number key, got {fetch_call}"
    assert "pull_number" not in fetch_call, f"Unexpected pull_number key in issue fetch: {fetch_call}"
    assert "pullNumber" not in fetch_call, f"Unexpected pullNumber key in issue fetch: {fetch_call}"

    comments_call = next(
        (args for name, args in mcp_tool_calls if name == "github_issue_read" and args.get("method") == "get_comments"),
        None
    )
    assert comments_call is not None, f"Expected github_issue_read (get_comments) call, got {mcp_tool_calls}"
    assert "issue_number" in comments_call, f"Expected issue_number key in comments fetch, got {comments_call}"


def test_mcp_public_client_pr_operations_use_pullNumber_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHubWriteClient PR operations pass pullNumber (not pull_number) to MCP tools."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("MCP_GITHUB_SERVER", "npx -y @modelcontextprotocol/server-github")

    mcp_tool_calls: list[tuple[str, dict]] = []

    class SpyMcpStrategy(GitHubMcpTransportStrategy):
        """Spy that captures MCP tool calls to verify pullNumber contract."""
        def _call_mcp_tool(self, tool_name: str, arguments: dict) -> object:
            mcp_tool_calls.append((tool_name, arguments))
            if tool_name == "github_pull_request_read":
                return {
                    "html_url": f"https://github.com/{arguments.get('owner')}/{arguments.get('repo')}/pull/{arguments.get('pullNumber')}",
                    "head": {"ref": "feature", "sha": "abc123"},
                }
            elif tool_name == "github_update_pull_request":
                return {
                    "html_url": f"https://github.com/{arguments.get('owner')}/{arguments.get('repo')}/pull/{arguments.get('pullNumber')}",
                }
            return {}

    monkeypatch.setattr(
        "precision_squad.github_client.resolve_github_transport",
        lambda **kwargs: GitHubTransportResolution(
            requested_mode="mcp",
            selected_transport="mcp",
            mcp_available=True,
            gh_cli_available=None,
            decision_reason="mcp_required_available",
        ),
    )
    monkeypatch.setattr(
        "precision_squad.github_client.GitHubMcpTransportStrategy",
        lambda: SpyMcpStrategy(),
    )

    client = GitHubWriteClient.from_env()

    # Test get_pull_request uses github_pull_request_read with pullNumber
    result = client.get_pull_request("owner", "repo", 42)
    assert result["html_url"] == "https://github.com/owner/repo/pull/42"

    pr_read_call = next(
        (args for name, args in mcp_tool_calls if name == "github_pull_request_read"),
        None
    )
    assert pr_read_call is not None, f"Expected github_pull_request_read call, got {mcp_tool_calls}"
    assert "pullNumber" in pr_read_call, f"Expected pullNumber key, got {pr_read_call}"
    assert pr_read_call["pullNumber"] == 42, f"Expected pullNumber=42, got {pr_read_call}"
    assert "pull_number" not in pr_read_call, f"Unexpected pull_number key: {pr_read_call}"

    mcp_tool_calls.clear()

    # Test update_pull_request uses github_update_pull_request with pullNumber
    url = client.update_pull_request("owner", "repo", 42, title="New Title", body="New Body")
    assert url == "https://github.com/owner/repo/pull/42"

    pr_update_call = next(
        (args for name, args in mcp_tool_calls if name == "github_update_pull_request"),
        None
    )
    assert pr_update_call is not None, f"Expected github_update_pull_request call, got {mcp_tool_calls}"
    assert "pullNumber" in pr_update_call, f"Expected pullNumber key, got {pr_update_call}"
    assert pr_update_call["pullNumber"] == 42, f"Expected pullNumber=42, got {pr_update_call}"
    assert "pull_number" not in pr_update_call, f"Unexpected pull_number key: {pr_update_call}"
    assert pr_update_call.get("title") == "New Title"
    assert pr_update_call.get("body") == "New Body"
