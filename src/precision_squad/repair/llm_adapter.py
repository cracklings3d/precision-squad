"""Compatibility direct-LLM repair adapter behind the shared seam."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import ApprovedPlan, IssueIntake, RepairResult, RunRecord
from ..stage_contracts import DeveloperStageContract


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
        return RepairResult(
            status="blocked",
            summary=(
                "Direct LLM compatibility path is retired on the current baseline. "
                "No repair output was applied to the workspace and no patch artifact "
                "was persisted for this path."
            ),
            detail_codes=(
                "direct_llm_runtime_retired",
                "repair_workspace_path_missing",
                "repair_patch_path_missing",
                "repair_output_not_applied",
            ),
        )
