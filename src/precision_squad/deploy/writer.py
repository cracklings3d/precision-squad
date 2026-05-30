"""Idempotent managed file writing for bootstrap operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .templates import DEFAULT_CONFIG_TEMPLATE, SKILL_TEMPLATE


class WriteOutcome(Enum):
    """Outcome of a managed file write operation."""

    CREATED = "created"
    UPDATED = "updated"
    REUSED = "reused"
    ALREADY_SATISFIED = "already_satisfied"


@dataclass
class ManagedFileConflict(Exception):
    """Raised when a managed file operation would conflict with existing unmanaged content."""

    path: Path
    message: str

    def __str__(self) -> str:
        return f"Conflict at {self.path}: {self.message}"


@dataclass(frozen=True)
class ManagedSurface:
    """Represents a managed file in the bootstrap surface."""

    path: Path
    content: str
    is_managed: bool = True


@dataclass
class _WriteResult:
    """Internal result of a single managed file write."""

    path: Path
    outcome: WriteOutcome


def _is_bootstrap_managed(path: Path, content: str) -> bool:
    """Detect if a file was previously written by bootstrap.

    A file is considered bootstrap-managed if:
    - It exists and contains the bootstrap marker comment, OR
    - Its path is within the .precision-squad/bootstrap/ directory
    """
    if not path.exists():
        return False
    if ".precision-squad" in path.parts and "bootstrap" in path.parts:
        return True
    existing = path.read_text(encoding="utf-8")
    if "# precision-squad managed config" in existing:
        return True
    if "# Precision Squad" in existing and "control plane" in existing:
        return True
    return False


def _load_existing_config(path: Path) -> str | None:
    """Load existing config content if the file exists."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def write_managed_surface(
    project_root: Path,
    *,
    force: bool = False,
) -> dict[str, WriteOutcome]:
    """Write the complete bootstrap managed surface idempotently.

    Args:
        project_root: The project root directory.
        force: If True, overwrite existing unmanaged files that differ.

    Returns:
        A dictionary mapping file paths to their write outcomes.

    Raises:
        ManagedFileConflict: If an unmanaged file would be overwritten.
    """
    results: dict[str, _WriteResult] = {}

    skill_path = project_root / "SKILL.md"
    config_dir = project_root / ".precision-squad"
    config_path = config_dir / "precision-squad.toml"
    bootstrap_meta_dir = config_dir / "bootstrap"
    bootstrap_meta_path = bootstrap_meta_dir / "bootstrap.json"

    root_config_path = project_root / ".precision-squad.toml"
    if root_config_path.exists():
        raise ManagedFileConflict(
            path=root_config_path,
            message=(
                f"Blocking root config file exists at {root_config_path}. "
                "Bootstrap uses .precision-squad/precision-squad.toml as the managed config "
                "location. "
                "Remove or rename the root .precision-squad.toml before running bootstrap."
            ),
        )

    skill_outcome = _write_skill_file(skill_path, force)
    results[str(skill_path)] = _WriteResult(path=skill_path, outcome=skill_outcome)

    config_dir.mkdir(exist_ok=True)
    config_outcome = _write_config_file(config_path)
    results[str(config_path)] = _WriteResult(path=config_path, outcome=config_outcome)

    bootstrap_meta_dir.mkdir(exist_ok=True)
    meta_outcome = _write_bootstrap_metadata(bootstrap_meta_path)
    results[str(bootstrap_meta_path)] = _WriteResult(path=bootstrap_meta_path, outcome=meta_outcome)

    return {path: result.outcome for path, result in results.items()}


def _write_skill_file(skill_path: Path, force: bool) -> WriteOutcome:
    """Write the SKILL.md file idempotently."""
    if skill_path.exists():
        existing = skill_path.read_text(encoding="utf-8")
        if existing == SKILL_TEMPLATE:
            return WriteOutcome.ALREADY_SATISFIED
        if _is_bootstrap_managed(skill_path, existing):
            if existing != SKILL_TEMPLATE:
                skill_path.write_text(SKILL_TEMPLATE, encoding="utf-8")
                return WriteOutcome.UPDATED
            return WriteOutcome.REUSED
        if not force:
            raise ManagedFileConflict(
                path=skill_path,
                message=(
                    "Existing SKILL.md is not managed by bootstrap. "
                    "Use --force to overwrite, or manually remove the existing file."
                ),
            )
        skill_path.write_text(SKILL_TEMPLATE, encoding="utf-8")
        return WriteOutcome.UPDATED

    skill_path.write_text(SKILL_TEMPLATE, encoding="utf-8")
    return WriteOutcome.CREATED


def _write_config_file(config_path: Path) -> WriteOutcome:
    """Write the precision-squad.toml config file idempotently."""
    existing = _load_existing_config(config_path)
    if existing is None:
        config_path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        return WriteOutcome.CREATED

    if existing == DEFAULT_CONFIG_TEMPLATE:
        return WriteOutcome.ALREADY_SATISFIED

    if _is_bootstrap_managed(config_path, existing):
        if existing != DEFAULT_CONFIG_TEMPLATE:
            config_path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
            return WriteOutcome.UPDATED
        return WriteOutcome.REUSED

    if existing.strip() == "":
        config_path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        return WriteOutcome.CREATED

    raise ManagedFileConflict(
        path=config_path,
        message=(
            f"Existing config at {config_path} is not managed by bootstrap. "
            "Remove or rename it before running bootstrap."
        ),
    )


def _write_bootstrap_metadata(meta_path: Path) -> WriteOutcome:
    """Write the bootstrap metadata file idempotently."""
    existing = _load_existing_config(meta_path)
    timestamp = datetime.now(timezone.utc).isoformat()

    if existing is not None:
        try:
            data = json.loads(existing)
            if isinstance(data, dict) and data.get("managed_by") == "precision-squad":
                if data.get("last_bootstrap") == timestamp:
                    return WriteOutcome.ALREADY_SATISFIED
                data["last_bootstrap"] = timestamp
                data["outcomes"] = {}
                meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return WriteOutcome.UPDATED
        except (json.JSONDecodeError, KeyError):
            pass

    metadata = {
        "managed_by": "precision-squad",
        "version": "1.0",
        "last_bootstrap": timestamp,
        "outcomes": {},
    }
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return WriteOutcome.CREATED


def describe_outcome(outcome: WriteOutcome) -> str:
    """Return a human-readable description of a write outcome."""
    descriptions = {
        WriteOutcome.CREATED: "created",
        WriteOutcome.UPDATED: "updated",
        WriteOutcome.REUSED: "reused",
        WriteOutcome.ALREADY_SATISFIED: "already satisfied",
    }
    return descriptions.get(outcome, str(outcome.value))
