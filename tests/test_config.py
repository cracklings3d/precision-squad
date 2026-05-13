"""Tests for config file support."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from precision_squad.config import (
    config_search_locations,
    format_config_search_locations,
    load_command_config,
    load_config,
    merge_config_into_args,
)


SUPPORTED_TABLES = {
    ("repair", "issue"): frozenset(
        {
            "runs_dir",
            "publish",
            "repo_path",
            "repair_agent",
            "repair_model",
            "review_model",
            "approved_plan_path",
        }
    ),
    ("publish", "run"): frozenset({"runs_dir", "review_model"}),
    ("install-skill",): frozenset({"project_root", "force"}),
}


def test_load_config_returns_empty_when_no_file(tmp_path: Path) -> None:
    result = load_config(tmp_path)
    assert result == {}


def test_load_config_from_toml_file(tmp_path: Path) -> None:
    config_file = tmp_path / ".precision-squad.toml"
    config_file.write_text(
        "[repair.issue]\nrepo_path = \"/tmp/repo\"\nrepair_agent = \"opencode\"\npublish = true\n",
        encoding="utf-8",
    )
    result = load_config(tmp_path)
    assert result == {
        "repair": {
            "issue": {
                "repo_path": "/tmp/repo",
                "repair_agent": "opencode",
                "publish": True,
            }
        }
    }


def test_load_command_config_from_root_file(tmp_path: Path) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        "[repair.issue]\nrepo_path = \"repo\"\nruns_dir = \"runs\"\n",
        encoding="utf-8",
    )

    result = load_command_config(
        start_dir=tmp_path,
        table=("repair", "issue"),
        supported_tables=SUPPORTED_TABLES,
    )

    assert result == {
        "repo_path": str((tmp_path / "repo").resolve()),
        "runs_dir": str((tmp_path / "runs").resolve()),
    }


def test_load_command_config_from_dot_precision_squad_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / ".precision-squad"
    config_dir.mkdir()
    config_file = config_dir / "precision-squad.toml"
    config_file.write_text(
        "[publish.run]\nruns_dir = \"runs\"\n",
        encoding="utf-8",
    )

    result = load_command_config(
        start_dir=tmp_path,
        table=("publish", "run"),
        supported_tables=SUPPORTED_TABLES,
    )

    assert result["runs_dir"] == str((config_dir / "runs").resolve())


def test_load_command_config_prefers_project_root_file(tmp_path: Path) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        "[repair.issue]\nrepo_path = \"root-repo\"\n",
        encoding="utf-8",
    )
    config_dir = tmp_path / ".precision-squad"
    config_dir.mkdir()
    (config_dir / "precision-squad.toml").write_text(
        "[repair.issue]\nrepo_path = \"nested-repo\"\n",
        encoding="utf-8",
    )

    result = load_command_config(
        start_dir=tmp_path,
        table=("repair", "issue"),
        supported_tables=SUPPORTED_TABLES,
    )

    assert result["repo_path"] == str((tmp_path / "root-repo").resolve())


def test_config_search_locations_match_documented_order(tmp_path: Path) -> None:
    assert config_search_locations(tmp_path) == (
        tmp_path.resolve() / ".precision-squad.toml",
        tmp_path.resolve() / ".precision-squad" / "precision-squad.toml",
    )


def test_format_config_search_locations_lists_supported_paths() -> None:
    assert format_config_search_locations() == (
        "./.precision-squad.toml or ./.precision-squad/precision-squad.toml"
    )


def test_load_config_invalid_toml(tmp_path: Path) -> None:
    config_file = tmp_path / ".precision-squad.toml"
    config_file.write_text("this is not valid toml [[[", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid config file format"):
        load_config(tmp_path)


def test_load_command_config_rejects_top_level_scalar_keys(tmp_path: Path) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        'repo_path = "."\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported top-level config key"):
        load_command_config(
            start_dir=tmp_path,
            table=("repair", "issue"),
            supported_tables=SUPPORTED_TABLES,
        )


def test_load_command_config_rejects_unknown_top_level_sections(tmp_path: Path) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        "[unknown.section]\nvalue = true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"Unknown config section \[unknown\]"):
        load_command_config(
            start_dir=tmp_path,
            table=("repair", "issue"),
            supported_tables=SUPPORTED_TABLES,
        )


def test_load_command_config_rejects_unknown_nested_sections(tmp_path: Path) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        "[repair.unknown]\nrepo_path = \"repo\"\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"Unknown config section \[repair.unknown\]"):
        load_command_config(
            start_dir=tmp_path,
            table=("repair", "issue"),
            supported_tables=SUPPORTED_TABLES,
        )


def test_load_command_config_rejects_empty_parent_namespace_sections(tmp_path: Path) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        "[repair]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"Unknown config section \[repair\]"):
        load_command_config(
            start_dir=tmp_path,
            table=("repair", "issue"),
            supported_tables=SUPPORTED_TABLES,
        )


def test_load_command_config_rejects_unknown_keys(tmp_path: Path) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        "[repair.issue]\nrepo_path = \"repo\"\nretry_from = \"run-123\"\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown config key 'retry_from'"):
        load_command_config(
            start_dir=tmp_path,
            table=("repair", "issue"),
            supported_tables=SUPPORTED_TABLES,
        )


def test_load_command_config_returns_only_active_command_table(tmp_path: Path) -> None:
    (tmp_path / ".precision-squad.toml").write_text(
        (
            "[repair.issue]\nrepo_path = \"repo\"\n"
            "[publish.run]\nruns_dir = \"runs\"\n"
            "[install-skill]\nproject_root = \"project\"\n"
        ),
        encoding="utf-8",
    )

    result = load_command_config(
        start_dir=tmp_path,
        table=("publish", "run"),
        supported_tables=SUPPORTED_TABLES,
    )

    assert result == {"runs_dir": str((tmp_path / "runs").resolve())}


def test_load_command_config_preserves_absolute_paths(tmp_path: Path) -> None:
    absolute_repo = (tmp_path / "external-repo").resolve()
    (tmp_path / ".precision-squad.toml").write_text(
        f'[repair.issue]\nrepo_path = "{absolute_repo.as_posix()}"\n',
        encoding="utf-8",
    )

    result = load_command_config(
        start_dir=tmp_path,
        table=("repair", "issue"),
        supported_tables=SUPPORTED_TABLES,
    )

    assert Path(result["repo_path"]) == absolute_repo


def test_load_command_config_resolves_approved_plan_path_relative_to_config_file(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".precision-squad"
    config_dir.mkdir()
    (config_dir / "precision-squad.toml").write_text(
        '[repair.issue]\napproved_plan_path = "plans/approved-plan.json"\n',
        encoding="utf-8",
    )

    result = load_command_config(
        start_dir=tmp_path,
        table=("repair", "issue"),
        supported_tables=SUPPORTED_TABLES,
    )

    assert result["approved_plan_path"] == str(
        (config_dir / "plans" / "approved-plan.json").resolve()
    )


def test_merge_config_fills_suppressed_values() -> None:
    config = {"repo_path": "/from/config", "repair_model": "gpt-4"}
    args = {
        "repo_path": argparse.SUPPRESS,
        "repair_model": argparse.SUPPRESS,
        "publish": False,
    }
    merged = merge_config_into_args(config, args)
    assert merged["repo_path"] == "/from/config"
    assert merged["repair_model"] == "gpt-4"


def test_merge_config_does_not_override_cli_values() -> None:
    config = {"repo_path": "/from/config"}
    args = {"repo_path": "/from/cli"}
    merged = merge_config_into_args(config, args)
    assert merged["repo_path"] == "/from/cli"


def test_merge_config_does_not_override_present_boolean_values() -> None:
    config = {"publish": True}
    args = {"publish": False}
    merged = merge_config_into_args(config, args)
    assert merged["publish"] is False


def test_merge_config_ignores_unknown_keys() -> None:
    config = {"unknown_key": "value"}
    args = {"repo_path": "/cli"}
    merged = merge_config_into_args(config, args)
    assert merged == {"repo_path": "/cli"}
