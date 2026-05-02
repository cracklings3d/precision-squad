"""Agent-backed repair stage using a documented local execution contract."""

import subprocess  # noqa: F401 — re-exported for test monkeypatching

from ..github_client import GitHubWriteClient
from .adapter import OpenCodeRepairAdapter, RepairAdapter
from .llm_adapter import OpenAIRepairAdapter
from .orchestration import (
    RepairStage,
    evaluate_docs_remediation_validation,
    merge_docs_remediation_execution_result,
    merge_execution_result,
    resolve_artifact_dir,
    run_docs_remediation_repair,
    run_repair_qa_loop,
    synthesis_artifacts_ready,
)
from .qa import WorkspaceQaVerifier, build_qa_feedback

__all__ = [
    "GitHubWriteClient",
    "OpenAIRepairAdapter",
    "OpenCodeRepairAdapter",
    "RepairAdapter",
    "RepairStage",
    "WorkspaceQaVerifier",
    "build_qa_feedback",
    "evaluate_docs_remediation_validation",
    "merge_docs_remediation_execution_result",
    "merge_execution_result",
    "resolve_artifact_dir",
    "run_docs_remediation_repair",
    "run_repair_qa_loop",
    "synthesis_artifacts_ready",
]
