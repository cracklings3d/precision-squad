"""Prerequisite validation for bootstrap operations."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BootstrapPrerequisiteError(Exception):
    """Raised when a bootstrap prerequisite is not satisfied."""

    message: str
    remediation: str | None = None

    def __str__(self) -> str:
        base = f"Bootstrap prerequisite failed: {self.message}"
        if self.remediation:
            base += f"\nRemediation: {self.remediation}"
        return base


def _check_github_credentials() -> tuple[bool, bool]:
    """Check GitHub credential prerequisites.

    Returns (missing_token, missing_app) where:
    - missing_token is True if neither GITHUB_TOKEN nor OpenCode_Github_Token is set
    - missing_app is True if opencode GitHub App is not configured (not checked here, always False)
    """
    missing_token = not os.getenv("GITHUB_TOKEN") and not os.getenv("OpenCode_Github_Token")
    missing_app = False  # Bootstrap does not require opencode GitHub App
    return missing_token, missing_app


@dataclass
class PrerequisiteChecker:
    """Validates bootstrap prerequisites for the Windows + opencode path."""

    project_root: Path
    _checked_opencode: bool = field(default=False, init=False)
    _opencode_available: bool = field(default=False, init=False)

    def check_all(self) -> None:
        """Validate all prerequisites; raises BootstrapPrerequisiteError on failure."""
        self._check_windows()
        self._check_project_root()
        self._check_precision_squad_cli()
        self._check_opencode()
        self._check_github_credentials()

    def _check_windows(self) -> None:
        """Verify Windows-only execution."""
        if platform.system() != "Windows":
            raise BootstrapPrerequisiteError(
                message="Bootstrap is supported only on Windows.",
                remediation="Run this command on a Windows system with PowerShell.",
            )

    def _check_project_root(self) -> None:
        """Verify project root is accessible for managed writes."""
        if not self.project_root.exists():
            raise BootstrapPrerequisiteError(
                message=f"Project root does not exist: {self.project_root}",
                remediation="Ensure the target directory exists before running bootstrap.",
            )
        if not self.project_root.is_dir():
            raise BootstrapPrerequisiteError(
                message=f"Project root is not a directory: {self.project_root}",
                remediation="Provide a valid directory path for --project-root.",
            )
        test_file = self.project_root / ".precision-squad-write-test"
        try:
            test_file.write_text("test", encoding="utf-8")
            test_file.unlink()
        except OSError as exc:
            raise BootstrapPrerequisiteError(
                message=f"Project root is not writable: {self.project_root}",
                remediation="Ensure the target directory has write permissions.",
            ) from exc

    def _check_precision_squad_cli(self) -> None:
        """Verify precision-squad CLI entrypoint is usable."""
        cli_path = self._find_precision_squad_cli()
        if cli_path is None:
            raise BootstrapPrerequisiteError(
                message="precision-squad CLI not found.",
                remediation=(
                    "Install precision-squad: pip install precision-squad "
                    "or run from a development checkout with PYTHONPATH set."
                ),
            )
        try:
            result = subprocess.run(
                [sys.executable, "-m", "precision_squad.cli", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise BootstrapPrerequisiteError(
                    message="precision-squad CLI is not functional.",
                    remediation="Reinstall precision-squad or check the installation.",
                )
        except subprocess.TimeoutExpired as exc:
            raise BootstrapPrerequisiteError(
                message="precision-squad CLI check timed out.",
                remediation="Check the installation and try again.",
            ) from exc
        except OSError as exc:
            raise BootstrapPrerequisiteError(
                message="Failed to execute precision-squad CLI.",
                remediation="Ensure Python is properly installed and accessible.",
            ) from exc

    def _find_precision_squad_cli(self) -> Path | None:
        """Locate the precision-squad CLI entrypoint."""
        if shutil.which("precision-squad") is not None:
            return Path(shutil.which("precision-squad") or "")
        cli_module = Path(self.project_root) / "src" / "precision_squad" / "cli.py"
        if cli_module.exists():
            return cli_module
        if shutil.which(sys.executable) is not None:
            result = subprocess.run(
                [sys.executable, "-c", "import precision_squad; print(precision_squad.__file__)"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                precision_squad_path = result.stdout.strip()
                if precision_squad_path:
                    return Path(precision_squad_path) / "cli.py"
        return None

    def _check_opencode(self) -> None:
        """Verify opencode availability."""
        if shutil.which("opencode") is not None:
            self._opencode_available = True
            self._checked_opencode = True
            return
        opencode_in_path = self._search_opencode_in_path()
        if opencode_in_path is not None:
            self._opencode_available = True
            self._checked_opencode = True
            return
        raise BootstrapPrerequisiteError(
            message="opencode not found.",
            remediation=(
                "Install opencode: see https://github.com/opencode-ai/opencode "
                "for installation instructions."
            ),
        )

    def _search_opencode_in_path(self) -> Path | None:
        """Search common locations for opencode executable."""
        if platform.system() != "Windows":
            return None
        common_locations = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "opencode" / "opencode.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "opencode" / "opencode.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "opencode" / "opencode.exe",
        ]
        for location in common_locations:
            if location.exists() and location.is_file():
                return location
        return None

    def _check_github_credentials(self) -> None:
        """Verify GitHub credential prerequisites using existing repair entrypoint rules."""
        missing_token, missing_app = _check_github_credentials()
        if missing_token:
            raise BootstrapPrerequisiteError(
                message="GitHub credentials are not configured.",
                remediation=(
                    "Set GITHUB_TOKEN environment variable with a GitHub Personal Access Token, "
                    "or configure opencode GitHub App credentials."
                ),
            )


def check_bootstrap_prerequisites(project_root: Path) -> None:
    """Validate all bootstrap prerequisites; raises BootstrapPrerequisiteError on failure."""
    checker = PrerequisiteChecker(project_root=project_root)
    checker.check_all()
