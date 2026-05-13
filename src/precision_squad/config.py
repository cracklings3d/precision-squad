"""Config file support for precision-squad CLI."""

from __future__ import annotations

import argparse
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ConfigTable = tuple[str, ...]

_CONFIG_CANDIDATES = (
    Path(".precision-squad.toml"),
    Path(".precision-squad") / "precision-squad.toml",
)

_PATH_LIKE_KEYS = frozenset({"approved_plan_path", "project_root", "repo_path", "runs_dir"})


def config_search_locations(start_dir: Path | None = None) -> tuple[Path, ...]:
    """Return supported config search locations relative to ``start_dir``."""
    search_root = (start_dir or Path.cwd()).resolve()
    return tuple(search_root / relative_path for relative_path in _CONFIG_CANDIDATES)


def format_config_search_locations() -> str:
    """Return supported config locations for user-facing messages."""
    display_paths = tuple(f"./{path.as_posix()}" for path in _CONFIG_CANDIDATES)
    return f"{display_paths[0]} or {display_paths[1]}"


def load_config(start_dir: Path | None = None) -> dict[str, Any]:
    """Return raw config file values, or an empty dict if no file is found."""
    config_path = _find_config_path(start_dir)
    if config_path is None:
        return {}
    return _parse_toml(config_path)


def load_command_config(
    *,
    start_dir: Path | None = None,
    table: ConfigTable,
    supported_tables: Mapping[ConfigTable, frozenset[str]],
) -> dict[str, Any]:
    """Load, validate, and return one command table from the config file."""
    config_path = _find_config_path(start_dir)
    if config_path is None:
        return {}

    config = _parse_toml(config_path)
    _validate_config_schema(config, path=config_path, supported_tables=supported_tables)

    return _resolve_relative_paths(
        _lookup_table(config, table),
        base_dir=config_path.parent,
    )


def _find_config_path(start_dir: Path | None = None) -> Path | None:
    for candidate in config_search_locations(start_dir):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _parse_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file and return the top-level table as a dict."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid config file format in {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Unable to read config file {path}: {exc}") from exc


def _validate_config_schema(
    config: Mapping[str, Any],
    *,
    path: Path,
    supported_tables: Mapping[ConfigTable, frozenset[str]],
) -> None:
    supported_sections = _format_supported_tables(supported_tables)

    for key, value in config.items():
        if not isinstance(value, Mapping):
            raise ValueError(
                f"Unsupported top-level config key {key!r} in {path}. "
                f"Use command tables {supported_sections}."
            )

        prefix = (key,)
        if not _has_matching_table(prefix, supported_tables):
            raise ValueError(
                f"Unknown config section {_format_table(prefix)} in {path}. "
                f"Supported sections: {supported_sections}."
            )

        _validate_section(
            value,
            prefix=prefix,
            path=path,
            supported_tables=supported_tables,
        )


def _validate_section(
    section: Mapping[str, Any],
    *,
    prefix: ConfigTable,
    path: Path,
    supported_tables: Mapping[ConfigTable, frozenset[str]],
) -> None:
    supported_sections = _format_supported_tables(supported_tables)
    allowed_keys = supported_tables.get(prefix)

    if allowed_keys is None:
        if not section:
            raise ValueError(
                f"Unknown config section {_format_table(prefix)} in {path}. "
                f"Supported sections: {supported_sections}."
            )

        expected_children = tuple(
            sorted(
                {
                    table[len(prefix)]
                    for table in supported_tables
                    if len(table) > len(prefix) and table[: len(prefix)] == prefix
                }
            )
        )
        expected_tables = ", ".join(_format_table(prefix + (child,)) for child in expected_children)

        for key, value in section.items():
            child_prefix = prefix + (key,)
            if not isinstance(value, Mapping):
                raise ValueError(
                    f"Unsupported config key {key!r} in section {_format_table(prefix)} in {path}. "
                    f"Use nested command tables {expected_tables}."
                )
            if not _has_matching_table(child_prefix, supported_tables):
                raise ValueError(
                    f"Unknown config section {_format_table(child_prefix)} in {path}. "
                    f"Supported sections: {supported_sections}."
                )
            _validate_section(
                value,
                prefix=child_prefix,
                path=path,
                supported_tables=supported_tables,
            )
        return

    for key, value in section.items():
        if isinstance(value, Mapping):
            child_prefix = prefix + (key,)
            raise ValueError(
                f"Unknown config section {_format_table(child_prefix)} in {path}. "
                f"Supported sections: {supported_sections}."
            )
        if key not in allowed_keys:
            raise ValueError(
                f"Unknown config key {key!r} in section {_format_table(prefix)} in {path}."
            )


def _has_matching_table(
    prefix: ConfigTable,
    supported_tables: Mapping[ConfigTable, frozenset[str]],
) -> bool:
    return any(table[: len(prefix)] == prefix for table in supported_tables)


def _lookup_table(config: Mapping[str, Any], table: ConfigTable) -> dict[str, Any]:
    node: Any = config
    for segment in table:
        if not isinstance(node, Mapping):
            return {}
        node = node.get(segment)
        if node is None:
            return {}

    if not isinstance(node, Mapping):
        return {}

    return dict(node)


def _resolve_relative_paths(section: dict[str, Any], *, base_dir: Path) -> dict[str, Any]:
    resolved = dict(section)
    for key in _PATH_LIKE_KEYS:
        value = resolved.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value)
        if path.is_absolute():
            continue
        resolved[key] = str((base_dir / path).resolve())
    return resolved


def _format_supported_tables(supported_tables: Mapping[ConfigTable, frozenset[str]]) -> str:
    return ", ".join(_format_table(table) for table in supported_tables)


def _format_table(table: ConfigTable) -> str:
    return f"[{'.'.join(table)}]"


def merge_config_into_args(
    config: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    """Merge config file values into CLI args.

    CLI args take precedence. Values absent from the CLI namespace are filled
    from the config file.
    """
    merged = dict(args)
    for key, config_value in config.items():
        if key not in merged:
            continue
        current = merged[key]
        if current is argparse.SUPPRESS:
            merged[key] = config_value
    return merged
