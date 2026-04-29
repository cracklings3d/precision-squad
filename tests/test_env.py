"""Tests for local environment loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from precision_squad.env import load_local_env


def test_load_local_env_reads_repo_root_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "GITHUB_TOKEN=test-github\nOPENAI_API_BASE_URL=https://example.invalid/v1\nCUSTOM_OPENAI_MODEL_NAME=test-model\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE_URL", raising=False)
    monkeypatch.delenv("CUSTOM_OPENAI_MODEL_NAME", raising=False)

    env_path = load_local_env(tmp_path)

    assert env_path == tmp_path / ".env"
    assert __import__("os").environ["GITHUB_TOKEN"] == "test-github"
    assert __import__("os").environ["OPENAI_API_BASE_URL"] == "https://example.invalid/v1"
    assert __import__("os").environ["CUSTOM_OPENAI_MODEL_NAME"] == "test-model"


def test_load_local_env_applies_github_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("OpenCode_Github_Token", "alias-token")

    load_local_env(tmp_path)

    assert __import__("os").environ["GITHUB_TOKEN"] == "alias-token"
