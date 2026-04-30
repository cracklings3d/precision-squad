"""Agent-backed repair stage using a documented local execution contract."""

import subprocess

from ..github_client import GitHubWriteClient
from .adapter import OpenCodeRepairAdapter
from .orchestration import (
    RepairStage,
    _resolve_rerun_branch,
    evaluate_docs_remediation_validation,
    merge_docs_remediation_execution_result,
    merge_execution_result,
    resolve_artifact_dir,
    run_docs_remediation_repair,
    run_repair_qa_loop,
    synthesis_artifacts_ready,
)
from .qa import WorkspaceQaVerifier, _failure_signature, _finalize_qa_result, build_qa_feedback

__all__ = [
    "OpenCodeRepairAdapter",
    "RepairStage",
    "WorkspaceQaVerifier",
    "GitHubWriteClient",
    "_failure_signature",
    "_finalize_qa_result",
    "_resolve_rerun_branch",
    "build_qa_feedback",
    "evaluate_docs_remediation_validation",
    "merge_docs_remediation_execution_result",
    "merge_execution_result",
    "resolve_artifact_dir",
    "run_docs_remediation_repair",
    "run_repair_qa_loop",
    "subprocess",
    "synthesis_artifacts_ready",
]
