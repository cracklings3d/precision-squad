"""Minimal local .env loading for precision-squad."""

from __future__ import annotations

import os
from pathlib import Path

ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "GITHUB_TOKEN": ("OpenCode_Github_Token",),
}


def load_local_env(start_dir: Path | None = None) -> Path | None:
    """Load key=value pairs from the nearest repo-root .env file."""
    root = _find_repo_root(start_dir or Path.cwd())
    env_path = root / ".env"
    if not env_path.exists():
        _apply_aliases()
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

    _apply_aliases()
    return env_path


def _find_repo_root(start_dir: Path) -> Path:
    current = start_dir.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src").exists():
            return candidate
    return start_dir.resolve()


def _apply_aliases() -> None:
    for target, aliases in ENV_ALIASES.items():
        if os.getenv(target):
            continue
        for alias in aliases:
            value = os.getenv(alias)
            if value:
                os.environ[target] = value
                break
