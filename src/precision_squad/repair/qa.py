"""QA verification helpers for repaired workspaces."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..models import ExecutionContract, QaResult


@dataclass(frozen=True, slots=True)
class QaFailureClassification:
    """Typed classification for a non-zero QA command result."""

    status: Literal["failed", "unrunnable"]
    summary: str
    detail_codes: tuple[str, ...]


class WorkspaceQaVerifier:
    """Runs a deterministic local QA check against a repaired workspace."""

    def verify(
        self,
        *,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
        iteration: int,
    ) -> QaResult:
        qa_stdout_path = run_dir / f"qa-{iteration}.stdout.log"
        qa_stderr_path = run_dir / f"qa-{iteration}.stderr.log"

        contract = _load_execution_contract(contract_artifact_dir)
        if contract is None:
            return QaResult(
                status="failed_infra",
                summary="QA verifier could not load the execution contract artifact.",
                detail_codes=("qa_contract_missing",),
                stdout_path=str(qa_stdout_path),
                stderr_path=str(qa_stderr_path),
            )
        if contract.qa_command is None:
            return QaResult(
                status="failed_infra",
                summary=(
                    "QA verifier could not find a documented QA command in the "
                    "execution contract."
                ),
                detail_codes=("qa_command_missing",),
                stdout_path=str(qa_stdout_path),
                stderr_path=str(qa_stderr_path),
            )
        command = contract.qa_command

        env = os.environ.copy()
        setup_stdout_chunks: list[str] = []
        setup_stderr_chunks: list[str] = []
        bootstrap_result = _ensure_whitelisted_tools_available(command, repo_workspace, env)
        if bootstrap_result is not None:
            qa_stdout_path.write_text("", encoding="utf-8", errors="ignore")
            qa_stderr_path.write_text(bootstrap_result, encoding="utf-8", errors="ignore")
            return QaResult(
                status="failed_infra",
                summary=(
                    "QA verifier could not make the documented QA toolchain "
                    "available locally."
                ),
                detail_codes=("qa_tool_bootstrap_failed",),
                command=command,
                stdout_path=str(qa_stdout_path),
                stderr_path=str(qa_stderr_path),
            )

        for setup_command in contract.setup_commands:
            setup_result = subprocess.run(
                ["pwsh", "-NoLogo", "-NoProfile", "-Command", setup_command],
                cwd=str(repo_workspace),
                env=env,
                capture_output=True,
                text=True,
            )
            setup_stdout_chunks.append(
                _format_qa_log_section(
                    f"Setup command stdout: {setup_command}", setup_result.stdout
                )
            )
            setup_stderr_chunks.append(
                _format_qa_log_section(
                    f"Setup command stderr: {setup_command}", setup_result.stderr
                )
            )
            if setup_result.returncode != 0:
                qa_stdout_path.write_text(
                    "".join(setup_stdout_chunks), encoding="utf-8", errors="ignore"
                )
                qa_stderr_path.write_text(
                    "".join(setup_stderr_chunks), encoding="utf-8", errors="ignore"
                )
                return QaResult(
                    status="failed_infra",
                    summary=(
                        "QA verifier could not complete the documented setup steps "
                        "in the repair workspace."
                    ),
                    detail_codes=("qa_environment_setup_failed",),
                    command=command,
                    stdout_path=str(qa_stdout_path),
                    stderr_path=str(qa_stderr_path),
                )

        completed = subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-Command", command],
            cwd=str(repo_workspace),
            env=env,
            capture_output=True,
            text=True,
        )
        qa_stdout_path.write_text(
            "".join(setup_stdout_chunks)
            + _format_qa_log_section("QA command stdout", completed.stdout),
            encoding="utf-8",
            errors="ignore",
        )
        qa_stderr_path.write_text(
            "".join(setup_stderr_chunks)
            + _format_qa_log_section("QA command stderr", completed.stderr),
            encoding="utf-8",
            errors="ignore",
        )

        if completed.returncode == 0:
            return QaResult(
                status="passed",
                summary="Documented QA command passed in the repair workspace.",
                detail_codes=("qa_passed",),
                command=command,
                stdout_path=str(qa_stdout_path),
                stderr_path=str(qa_stderr_path),
            )

        classification = _classify_qa_command_failure(
            completed.stdout, completed.stderr, command
        )
        return QaResult(
            status=classification.status,
            summary=classification.summary,
            detail_codes=classification.detail_codes,
            command=command,
            stdout_path=str(qa_stdout_path),
            stderr_path=str(qa_stderr_path),
        )


def build_qa_feedback(qa_result: QaResult) -> str:
    stdout_excerpt = ""
    stderr_excerpt = ""
    if qa_result.stdout_path:
        stdout_excerpt = Path(qa_result.stdout_path).read_text(encoding="utf-8", errors="ignore")
    if qa_result.stderr_path:
        stderr_excerpt = Path(qa_result.stderr_path).read_text(encoding="utf-8", errors="ignore")
    excerpt = (stdout_excerpt + "\n" + stderr_excerpt).strip()
    excerpt = excerpt[-4000:]
    return "\n".join(
        [
            f"QA command: {qa_result.command}",
            f"QA summary: {qa_result.summary}",
            "QA output excerpt:",
            excerpt,
        ]
    )


def _format_qa_log_section(title: str, content: str) -> str:
    body = content.rstrip()
    return f"===== {title} =====\n{body}\n"


def _run_baseline_qa(
    *,
    repo_path: Path,
    run_dir: Path,
    contract_artifact_dir: Path,
    verifier: WorkspaceQaVerifier,
    rerun_branch: str | None = None,
    rerun_remote_url: str | None = None,
) -> QaResult:
    from .orchestration import _reset_workspace_to_rerun_branch

    baseline_workspace = (run_dir / "baseline-workspace").resolve()
    baseline_repo = (baseline_workspace / "repo").resolve()
    baseline_workspace.mkdir(parents=True, exist_ok=True)
    if baseline_repo.exists():
        shutil.rmtree(baseline_repo)

    clone_result = subprocess.run(
        ["git", "clone", "--no-hardlinks", str(repo_path.resolve()), str(baseline_repo)],
        cwd=str(baseline_workspace),
        capture_output=True,
        text=True,
    )
    if clone_result.returncode != 0:
        return QaResult(
            status="failed_infra",
            summary="Baseline QA could not clone the source repository.",
            detail_codes=("baseline_clone_failed",),
            phase="baseline",
        )

    rerun_reset_error = _reset_workspace_to_rerun_branch(
        baseline_repo,
        branch_name=rerun_branch,
        remote_url=rerun_remote_url,
    )
    if rerun_reset_error is not None:
        return QaResult(
            status="failed_infra",
            summary=rerun_reset_error,
            detail_codes=("baseline_rerun_branch_unavailable",),
            phase="baseline",
        )

    result = verifier.verify(
        run_dir=run_dir,
        contract_artifact_dir=contract_artifact_dir,
        repo_workspace=baseline_repo,
        iteration=0,
    )
    return QaResult(
        status=result.status,
        summary=result.summary,
        detail_codes=result.detail_codes,
        command=result.command,
        stdout_path=result.stdout_path,
        stderr_path=result.stderr_path,
        phase="baseline",
    )


def _finalize_qa_result(
    *,
    qa_result: QaResult,
    baseline_result: QaResult,
    baseline_failure_signature: frozenset[str],
) -> QaResult:
    final_result = QaResult(
        status=qa_result.status,
        summary=qa_result.summary,
        detail_codes=qa_result.detail_codes,
        command=qa_result.command,
        stdout_path=qa_result.stdout_path,
        stderr_path=qa_result.stderr_path,
        phase="final",
    )
    if baseline_result.status not in {"failed", "failed_infra"}:
        return final_result

    repaired_failure_signature = _failure_signature(qa_result)
    if repaired_failure_signature < baseline_failure_signature:
        return QaResult(
            status="provisional",
            summary=(
                "Repair QA improved on the baseline failure set without introducing "
                "new failures, but the suite is not fully green."
            ),
            detail_codes=("qa_baseline_improved",),
            command=qa_result.command,
            stdout_path=qa_result.stdout_path,
            stderr_path=qa_result.stderr_path,
            phase="final",
        )

    return final_result


def _failure_signature(qa_result: QaResult) -> frozenset[str]:
    combined_output = ""
    if qa_result.stdout_path and Path(qa_result.stdout_path).exists():
        combined_output += Path(qa_result.stdout_path).read_text(encoding="utf-8", errors="ignore")
    if qa_result.stderr_path and Path(qa_result.stderr_path).exists():
        combined_output += "\n" + Path(qa_result.stderr_path).read_text(
            encoding="utf-8", errors="ignore"
        )

    markers: set[str] = set()
    for line in combined_output.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("ERROR "):
            markers.add(text)
        elif text.startswith("E   "):
            markers.add(text)
    return frozenset(markers)


def _load_execution_contract(contract_artifact_dir: Path) -> ExecutionContract | None:
    contract_path = contract_artifact_dir / "contract.json"
    if not contract_path.exists():
        return None
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    setup_commands = payload.get("setup_commands", [])
    notes = payload.get("notes", [])
    questions = payload.get("questions", [])
    return ExecutionContract(
        source_path=payload.get("source_path"),
        setup_commands=tuple(str(item) for item in setup_commands),
        qa_command=payload.get("qa_command"),
        notes=tuple(str(item) for item in notes),
        questions=tuple(str(item) for item in questions),
    )


def _ensure_whitelisted_tools_available(
    command: str, repo_workspace: Path, env: dict[str, str]
) -> str | None:
    tool_name = _leading_tool(command)
    if tool_name not in {"uv", "poetry"}:
        return None

    probe = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-Command", f"{tool_name} --version"],
        cwd=str(repo_workspace),
        env=env,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        return None

    install_command = f"python -m pip install {tool_name}"
    installed = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-Command", install_command],
        cwd=str(repo_workspace),
        env=env,
        capture_output=True,
        text=True,
    )
    if installed.returncode == 0:
        return None

    return (
        f"Could not install required QA tool `{tool_name}`. The documented QA "
        f"command is `{command}`, so the workflow tried the whitelisted bootstrap "
        f"command `{install_command}` and it failed. A newcomer would now ask: "
        "is this tool really part of the documented setup, and if so, what exact "
        "installation command should they run on Windows?\n\n"
        f"stdout:\n{installed.stdout}\n\nstderr:\n{installed.stderr}"
    )


def _leading_tool(command: str) -> str:
    stripped = command.strip()
    if not stripped:
        return ""
    return stripped.split(maxsplit=1)[0]


def _classify_qa_command_failure(
    stdout: str, stderr: str, command: str
) -> QaFailureClassification:
    combined = f"{stdout}\n{stderr}".lower()

    unrunnable_markers = (
        "commandnotfoundexception",
        "is not recognized as the name of a cmdlet",
        "usage: pytest",
        "error: unrecognized arguments:",
        "error: file or directory not found:",
        "collected 0 items",
        "no tests ran",
        "no tests collected",
        "importerror while loading conftest",
        "pytestusageerror",
    )
    if any(marker in combined for marker in unrunnable_markers):
        return QaFailureClassification(
            status="unrunnable",
            summary=(
                "The documented QA command did not produce a trustworthy verification "
                "signal. It appears to have failed before actually verifying the fix."
            ),
            detail_codes=("qa_command_unrunnable",),
        )

    if "pytest" in command.lower():
        if "failed" in combined or "error" in combined:
            return QaFailureClassification(
                status="failed",
                summary=(
                    "Documented QA command ran and reported failing checks in the "
                    "repair workspace."
                ),
                detail_codes=("qa_failed",),
            )
        return QaFailureClassification(
            status="unrunnable",
            summary=(
                "The documented QA command exited non-zero, but the output does not "
                "clearly show that it reached a valid verification result."
            ),
            detail_codes=("qa_command_unrunnable",),
        )

    return QaFailureClassification(
        status="unrunnable",
        summary=(
            "The documented QA command exited non-zero without a clear verification "
            "result. Treating this as an unrunnable verification command instead of "
            "a real failing check."
        ),
        detail_codes=("qa_command_unrunnable",),
    )
