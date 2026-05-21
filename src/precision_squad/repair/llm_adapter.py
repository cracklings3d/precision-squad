"""Compatibility direct-LLM repair adapter behind the shared seam."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import openai
from jsonschema import ValidationError, validate

from ..models import ApprovedPlan, DesignDecision, IssueIntake, RepairResult, RunRecord, SideIssue
from ..stage_contracts import DeveloperStageContract
from .adapter import (
    REPAIR_RESULT_SCHEMA,
    _build_repair_prompt,
    _extract_design_decisions,
    _extract_side_issues,
)

_SYSTEM_PROMPT = (
    "You are a precise code repair assistant. "
    "You will receive an issue description and context files. "
    "Make the minimal source changes needed to resolve the issue. "
    "Output a single JSON object matching the schema provided in the user prompt. "
    "Do not output any text outside the JSON object."
)


@dataclass(frozen=True, slots=True)
class VercelAIRepairAdapter:
    """Repair adapter that calls an OpenAI-compatible LLM API directly."""

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
        stdout_path = run_dir / "repair.stdout.log"

        prompt = _build_repair_prompt(
            approved_plan=approved_plan,
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
            repo_workspace=repo_workspace,
            qa_feedback=self.qa_feedback,
            developer_contract=developer_contract,
        )

        resolved_model = self.model or os.environ.get("OPENAI_MODEL", "gpt-4o")

        try:
            client = openai.OpenAI()
            response = client.chat.completions.create(
                model=resolved_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            raw_content = response.choices[0].message.content or "{}"
        except Exception as exc:
            return RepairResult(
                status="failed_infra",
                summary=f"LLM API call failed: {exc}",
                detail_codes=("llm_api_failed",),
                stdout_path=str(stdout_path),
            )

        stdout_path.write_text(raw_content, encoding="utf-8")

        repair_json = _parse_llm_response(raw_content)
        side_issues: tuple[SideIssue, ...] = ()
        design_decisions: tuple[DesignDecision, ...] = ()
        if repair_json is not None:
            side_issues = _extract_side_issues(repair_json)
            design_decisions = _extract_design_decisions(repair_json)

        if repair_json is None:
            return RepairResult(
                status="blocked",
                summary="LLM response did not match the expected repair result schema.",
                detail_codes=("llm_response_invalid",),
                stdout_path=str(stdout_path),
            )

        return RepairResult(
            status="blocked",
            summary=(
                f"{repair_json.get('summary', 'Repair agent returned structured output.')} "
                "Direct LLM output was not applied to the workspace and did not persist "
                "a patch artifact for this run."
            ),
            detail_codes=(
                "repair_workspace_path_missing",
                "repair_patch_path_missing",
                "repair_output_not_applied",
            ),
            stdout_path=str(stdout_path),
            side_issues=side_issues,
            design_decisions=design_decisions,
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
