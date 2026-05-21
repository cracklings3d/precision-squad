"""Compatibility direct-LLM repair adapter behind the shared seam."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import openai
from jsonschema import ValidationError, validate

from ..models import ApprovedPlan, IssueIntake, RepairResult, RunRecord
from ..stage_contracts import DeveloperStageContract
from .adapter import REPAIR_RESULT_SCHEMA

_LEGACY_OPENAI_CLIENT_FACTORY = openai.OpenAI
_RETIRED_COMPATIBILITY_SUMMARY = (
    "vercel-ai is a retired compatibility path and not an active supported repair mode. "
    "Direct LLM output was not applied to the workspace and did not persist a patch artifact "
    "for this run."
)


@dataclass(frozen=True, slots=True)
class VercelAIRepairAdapter:
    """Compatibility adapter for the retired direct-LLM repair path."""

    model: str | None = None
    qa_feedback: str | None = None

    def with_qa_feedback(self, feedback: str) -> VercelAIRepairAdapter:
        """Return a copy of this adapter with the given QA feedback."""
        return VercelAIRepairAdapter(model=self.model, qa_feedback=feedback)

    def repair(
        self,
        *,
        approved_plan: ApprovedPlan | None = None,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
        repo_workspace: Path,
        developer_contract: DeveloperStageContract | None = None,
    ) -> RepairResult:
        del approved_plan, intake, run_record, contract_artifact_dir, repo_workspace, developer_contract
        stdout_path = run_dir / "repair.stdout.log"
        stdout_path.write_text(_RETIRED_COMPATIBILITY_SUMMARY, encoding="utf-8")

        return RepairResult(
            status="blocked",
            summary=_RETIRED_COMPATIBILITY_SUMMARY,
            detail_codes=(
                "repair_workspace_path_missing",
                "repair_patch_path_missing",
                "repair_output_not_applied",
            ),
            stdout_path=str(stdout_path),
        )


def _parse_llm_response(raw_content: str) -> dict | None:
    """Parse and validate a single JSON response from an LLM."""
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        validate(instance=payload, schema=REPAIR_RESULT_SCHEMA)
    except ValidationError:
        return None
    return payload
