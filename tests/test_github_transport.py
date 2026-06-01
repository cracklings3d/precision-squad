"""Tests for GitHub transport selection."""

from __future__ import annotations

from importlib.machinery import ModuleSpec

import pytest

from precision_squad.github_transport import (
    GitHubTransportResolution,
    GitHubTransportSelectionError,
    _probe_mcp_available,
    reset_github_transport_resolution_cache,
    resolve_github_transport,
)


@pytest.fixture(autouse=True)
def reset_transport_cache() -> None:
    reset_github_transport_resolution_cache()


def test_auto_selects_mcp_when_available() -> None:
    resolution = resolve_github_transport(
        "auto",
        probe_mcp_available=lambda: True,
        probe_gh_cli_available=lambda: pytest.fail("gh probe should not run"),
    )

    assert resolution == GitHubTransportResolution(
        requested_mode="auto",
        selected_transport="mcp",
        mcp_available=True,
        gh_cli_available=None,
        decision_reason="auto_selected_mcp",
    )


def test_auto_selects_cli_when_mcp_is_unavailable() -> None:
    resolution = resolve_github_transport(
        "auto",
        probe_mcp_available=lambda: False,
        probe_gh_cli_available=lambda: True,
    )

    assert resolution == GitHubTransportResolution(
        requested_mode="auto",
        selected_transport="cli",
        mcp_available=False,
        gh_cli_available=True,
        decision_reason="auto_selected_cli",
    )


def test_auto_errors_when_no_transport_is_available() -> None:
    with pytest.raises(GitHubTransportSelectionError) as exc_info:
        resolve_github_transport(
            "auto",
            probe_mcp_available=lambda: False,
            probe_gh_cli_available=lambda: False,
        )

    assert exc_info.value.code == "github_transport_unavailable"
    assert exc_info.value.requested_mode == "auto"
    assert exc_info.value.decision_reason == "auto_no_transport_available"


def test_mcp_mode_errors_without_cli_fallback() -> None:
    gh_probed = False

    def gh_probe() -> bool:
        nonlocal gh_probed
        gh_probed = True
        return True

    with pytest.raises(GitHubTransportSelectionError) as exc_info:
        resolve_github_transport(
            "mcp",
            probe_mcp_available=lambda: False,
            probe_gh_cli_available=gh_probe,
        )

    assert exc_info.value.code == "github_transport_mcp_unavailable"
    assert exc_info.value.decision_reason == "mcp_required_unavailable"
    assert gh_probed is False


def test_cli_mode_errors_when_cli_is_unavailable() -> None:
    with pytest.raises(GitHubTransportSelectionError) as exc_info:
        resolve_github_transport(
            "cli",
            probe_mcp_available=lambda: pytest.fail("mcp probe should not run"),
            probe_gh_cli_available=lambda: False,
        )

    assert exc_info.value.code == "github_transport_cli_unavailable"
    assert exc_info.value.requested_mode == "cli"
    assert exc_info.value.decision_reason == "cli_required_unavailable"


def test_invalid_mode_is_rejected_deterministically() -> None:
    with pytest.raises(GitHubTransportSelectionError) as exc_info:
        resolve_github_transport("http")

    assert exc_info.value.code == "github_transport_invalid_mode"
    assert exc_info.value.decision_reason == "invalid_requested_mode"


def test_resolution_is_cached_once_per_run() -> None:
    probe_calls = {"mcp": 0, "gh": 0}

    def mcp_probe() -> bool:
        probe_calls["mcp"] += 1
        return False

    def gh_probe() -> bool:
        probe_calls["gh"] += 1
        return True

    first = resolve_github_transport(
        "auto",
        probe_mcp_available=mcp_probe,
        probe_gh_cli_available=gh_probe,
    )
    second = resolve_github_transport(
        "auto",
        probe_mcp_available=lambda: pytest.fail("mcp probe should be cached"),
        probe_gh_cli_available=lambda: pytest.fail("gh probe should be cached"),
    )

    assert first is second
    assert probe_calls == {"mcp": 1, "gh": 1}


def test_terminal_failure_is_cached_once_per_run() -> None:
    probe_calls = {"mcp": 0, "gh": 0}

    def mcp_probe() -> bool:
        probe_calls["mcp"] += 1
        return False

    def gh_probe() -> bool:
        probe_calls["gh"] += 1
        return False

    with pytest.raises(GitHubTransportSelectionError) as first_error:
        resolve_github_transport(
            "auto",
            probe_mcp_available=mcp_probe,
            probe_gh_cli_available=gh_probe,
        )

    with pytest.raises(GitHubTransportSelectionError) as second_error:
        resolve_github_transport(
            "auto",
            probe_mcp_available=lambda: pytest.fail("mcp probe should be cached"),
            probe_gh_cli_available=lambda: pytest.fail("gh probe should be cached"),
        )

    assert second_error.value is first_error.value
    assert probe_calls == {"mcp": 1, "gh": 1}


def test_explicit_mode_does_not_reuse_cached_auto_resolution() -> None:
    auto = resolve_github_transport(
        "auto",
        probe_mcp_available=lambda: False,
        probe_gh_cli_available=lambda: True,
    )

    with pytest.raises(GitHubTransportSelectionError) as exc_info:
        resolve_github_transport(
            "mcp",
            probe_mcp_available=lambda: False,
            probe_gh_cli_available=lambda: pytest.fail("gh probe should not run for mcp"),
        )

    assert auto.selected_transport == "cli"
    assert exc_info.value.code == "github_transport_mcp_unavailable"
    assert exc_info.value.requested_mode == "mcp"


def test_explicit_mode_keeps_own_cached_result() -> None:
    probe_calls = {"mcp": 0, "gh": 0}

    def gh_probe() -> bool:
        probe_calls["gh"] += 1
        return True

    def mcp_probe() -> bool:
        probe_calls["mcp"] += 1
        return True

    resolve_github_transport(
        "auto",
        probe_mcp_available=lambda: False,
        probe_gh_cli_available=gh_probe,
    )
    first = resolve_github_transport("mcp", probe_mcp_available=mcp_probe)
    second = resolve_github_transport(
        "mcp",
        probe_mcp_available=lambda: pytest.fail("mcp result should be cached for mcp mode"),
    )

    assert first is second
    assert first.selected_transport == "mcp"
    assert probe_calls == {"mcp": 1, "gh": 1}


def test_probe_mcp_available_returns_false_when_mcp_module_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("precision_squad.github_transport.find_spec", lambda name: None)

    assert _probe_mcp_available() is False


def test_probe_mcp_available_returns_true_when_mcp_package_and_server_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP is available only when BOTH mcp package AND MCP_GITHUB_SERVER are present."""
    monkeypatch.setattr(
        "precision_squad.github_transport.find_spec",
        lambda name: ModuleSpec(name, loader=None),
    )
    monkeypatch.setenv("MCP_GITHUB_SERVER", "npx -y @modelcontextprotocol/server-github")

    assert _probe_mcp_available() is True


def test_probe_mcp_available_returns_false_when_mcp_package_present_but_server_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP is NOT available if mcp package exists but MCP_GITHUB_SERVER is not set.

    This is the key auto-fallback semantics: having the mcp Python package importable
    does not mean MCP is runnable. MCP requires MCP_GITHUB_SERVER to be configured.
    So auto mode must NOT select MCP in this case and should fall back to CLI.
    """
    monkeypatch.setattr(
        "precision_squad.github_transport.find_spec",
        lambda name: ModuleSpec(name, loader=None),
    )
    monkeypatch.delenv("MCP_GITHUB_SERVER", raising=False)

    assert _probe_mcp_available() is False


def test_auto_falls_back_to_cli_when_mcp_package_present_but_server_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto mode must NOT select MCP when only package importability is present.

    Even if find_spec("mcp") succeeds, if MCP_GITHUB_SERVER is not set,
    MCP is not runnable. Auto must fall back to CLI if CLI is available.
    """
    # MCP package importable but no MCP_GITHUB_SERVER
    monkeypatch.setattr(
        "precision_squad.github_transport.find_spec",
        lambda name: ModuleSpec(name, loader=None) if name == "mcp" else None,
    )
    monkeypatch.delenv("MCP_GITHUB_SERVER", raising=False)

    resolution = resolve_github_transport(
        "auto",
        probe_mcp_available=_probe_mcp_available,
        probe_gh_cli_available=lambda: True,
    )

    assert resolution.selected_transport == "cli"
    assert resolution.decision_reason == "auto_selected_cli"
    assert resolution.mcp_available is False


def test_forced_mcp_fails_explicitly_when_server_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forced mcp mode must fail explicitly when MCP_GITHUB_SERVER is not set.

    Even if the mcp Python package is importable, without MCP_GITHUB_SERVER
    being configured, MCP transport is not runnable and must raise an error.
    """
    # MCP package importable but no MCP_GITHUB_SERVER
    monkeypatch.setattr(
        "precision_squad.github_transport.find_spec",
        lambda name: ModuleSpec(name, loader=None) if name == "mcp" else None,
    )
    monkeypatch.delenv("MCP_GITHUB_SERVER", raising=False)

    with pytest.raises(GitHubTransportSelectionError) as exc_info:
        resolve_github_transport(
            "mcp",
            probe_mcp_available=_probe_mcp_available,
            probe_gh_cli_available=lambda: True,
        )

    assert exc_info.value.code == "github_transport_mcp_unavailable"
    assert exc_info.value.decision_reason == "mcp_required_unavailable"
