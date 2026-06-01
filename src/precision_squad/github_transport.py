"""GitHub transport selection seam for per-run resolution."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Literal, cast

GitHubTransportMode = Literal["auto", "mcp", "cli"]
GitHubTransportName = Literal["mcp", "cli"]
GitHubTransportDecisionReason = Literal[
    "auto_selected_mcp",
    "auto_selected_cli",
    "auto_no_transport_available",
    "mcp_required_available",
    "mcp_required_unavailable",
    "cli_required_available",
    "cli_required_unavailable",
    "invalid_requested_mode",
]


@dataclass(frozen=True, slots=True)
class GitHubTransportResolution:
    """Resolved GitHub transport metadata for the current run."""

    requested_mode: GitHubTransportMode
    selected_transport: GitHubTransportName
    mcp_available: bool | None
    gh_cli_available: bool | None
    decision_reason: GitHubTransportDecisionReason


class GitHubTransportSelectionError(RuntimeError):
    """Raised when GitHub transport selection cannot succeed."""

    def __init__(
        self,
        *,
        code: str,
        requested_mode: str,
        summary: str,
        decision_reason: GitHubTransportDecisionReason,
    ) -> None:
        super().__init__(summary)
        self.code = code
        self.requested_mode = requested_mode
        self.summary = summary
        self.decision_reason = decision_reason


_cached_resolutions: dict[GitHubTransportMode, GitHubTransportResolution] = {}
_cached_errors: dict[GitHubTransportMode, GitHubTransportSelectionError] = {}


def resolve_github_transport(
    requested_mode: GitHubTransportMode | str | None = None,
    *,
    probe_mcp_available: Callable[[], bool] | None = None,
    probe_gh_cli_available: Callable[[], bool] | None = None,
) -> GitHubTransportResolution:
    """Resolve and cache the GitHub transport for the current run."""

    mode = _normalize_requested_mode(requested_mode)

    cached_resolution = _cached_resolutions.get(mode)
    if cached_resolution is not None:
        return cached_resolution

    cached_error = _cached_errors.get(mode)
    if cached_error is not None:
        raise cached_error

    mcp_probe = probe_mcp_available or _probe_mcp_available
    gh_cli_probe = probe_gh_cli_available or _probe_gh_cli_available

    try:
        resolution = _resolve_uncached(
            mode,
            mcp_probe=mcp_probe,
            gh_cli_probe=gh_cli_probe,
        )
    except GitHubTransportSelectionError as exc:
        _cached_errors[mode] = exc
        raise

    _cached_resolutions[mode] = resolution
    return resolution


def _resolve_uncached(
    requested_mode: GitHubTransportMode,
    *,
    mcp_probe: Callable[[], bool],
    gh_cli_probe: Callable[[], bool],
) -> GitHubTransportResolution:
    if requested_mode == "auto":
        mcp_available = mcp_probe()
        if mcp_available:
            return GitHubTransportResolution(
                requested_mode="auto",
                selected_transport="mcp",
                mcp_available=True,
                gh_cli_available=None,
                decision_reason="auto_selected_mcp",
            )

        gh_cli_available = gh_cli_probe()
        if gh_cli_available:
            return GitHubTransportResolution(
                requested_mode="auto",
                selected_transport="cli",
                mcp_available=False,
                gh_cli_available=True,
                decision_reason="auto_selected_cli",
            )

        raise GitHubTransportSelectionError(
            code="github_transport_unavailable",
            requested_mode="auto",
            summary="GitHub transport selection failed: neither MCP nor gh CLI is available.",
            decision_reason="auto_no_transport_available",
        )

    if requested_mode == "mcp":
        mcp_available = mcp_probe()
        if mcp_available:
            return GitHubTransportResolution(
                requested_mode="mcp",
                selected_transport="mcp",
                mcp_available=True,
                gh_cli_available=None,
                decision_reason="mcp_required_available",
            )

        raise GitHubTransportSelectionError(
            code="github_transport_mcp_unavailable",
            requested_mode="mcp",
            summary=(
                "GitHub transport selection failed: MCP transport was required "
                "but is unavailable."
            ),
            decision_reason="mcp_required_unavailable",
        )

    gh_cli_available = gh_cli_probe()
    if gh_cli_available:
        return GitHubTransportResolution(
            requested_mode="cli",
            selected_transport="cli",
            mcp_available=None,
            gh_cli_available=True,
            decision_reason="cli_required_available",
        )

    raise GitHubTransportSelectionError(
        code="github_transport_cli_unavailable",
        requested_mode="cli",
        summary=(
            "GitHub transport selection failed: gh CLI transport was required "
            "but is unavailable."
        ),
        decision_reason="cli_required_unavailable",
    )


def _normalize_requested_mode(
    requested_mode: GitHubTransportMode | str | None,
) -> GitHubTransportMode:
    if requested_mode is None:
        requested_mode = os.getenv("GITHUB_TRANSPORT")
        if requested_mode is None or not requested_mode.strip():
            return "auto"

    normalized = requested_mode.strip().lower()
    if normalized not in {"auto", "mcp", "cli"}:
        raise GitHubTransportSelectionError(
            code="github_transport_invalid_mode",
            requested_mode=requested_mode,
            summary=(
                "Invalid GITHUB_TRANSPORT value "
                f"{requested_mode!r}. Expected one of: auto, mcp, cli."
            ),
            decision_reason="invalid_requested_mode",
        )
    return cast(GitHubTransportMode, normalized)


def _probe_mcp_available() -> bool:
    """Return whether an MCP GitHub transport is currently available and runnable.

    MCP availability requires BOTH:
    1. The mcp Python package must be importable (find_spec succeeds)
    2. The MCP_GITHUB_SERVER environment variable must be set (server command)

    Without both conditions, MCP is not a usable transport even if the package
    is installed, so auto mode must fall back to CLI.
    """

    if find_spec("mcp") is None:
        return False

    # MCP package is present - check if runtime server is configured
    # MCP is only runnable when MCP_GITHUB_SERVER env var is set
    return bool(os.environ.get("MCP_GITHUB_SERVER"))


def _probe_gh_cli_available() -> bool:
    """Return whether gh CLI is currently available on PATH."""

    return shutil.which("gh") is not None


def reset_github_transport_resolution_cache() -> None:
    """Reset cached GitHub transport state for tests."""

    _cached_resolutions.clear()
    _cached_errors.clear()
