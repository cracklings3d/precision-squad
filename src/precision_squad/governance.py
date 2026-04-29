"""Deterministic evaluation and governance rules for V1."""

from __future__ import annotations

from .models import EvaluationResult, ExecutionResult, GovernanceVerdict, IssueIntake


def evaluate_run(intake: IssueIntake, execution_result: ExecutionResult) -> EvaluationResult:
    """Normalize execution output into the first evaluation result."""
    del intake

    if execution_result.status == "failed_infra":
        return EvaluationResult(
            status="failed_infra",
            summary=execution_result.summary,
            detail_codes=execution_result.detail_codes,
        )

    if execution_result.status == "completed":
        return EvaluationResult(
            status="success",
            summary=execution_result.summary,
            detail_codes=execution_result.detail_codes,
        )

    return EvaluationResult(
        status="blocked",
        summary=execution_result.summary,
        detail_codes=execution_result.detail_codes,
    )


def apply_governance(
    intake: IssueIntake,
    execution_result: ExecutionResult | None,
    evaluation_result: EvaluationResult | None,
) -> GovernanceVerdict:
    """Apply the first deterministic governance rules."""
    reason_codes: list[str] = []

    if intake.assessment.status == "blocked":
        reason_codes.extend(intake.assessment.reason_codes)
        return GovernanceVerdict(
            status="blocked",
            summary="Issue intake is blocked and cannot proceed to execution.",
            reason_codes=tuple(reason_codes),
        )

    if execution_result is None:
        return GovernanceVerdict(
            status="blocked",
            summary="Missing execution result artifact.",
            reason_codes=("missing_execution_result",),
        )

    if evaluation_result is None:
        return GovernanceVerdict(
            status="blocked",
            summary="Missing evaluation result artifact.",
            reason_codes=("missing_evaluation_result",),
        )

    if evaluation_result.status != "success":
        reason_codes.extend(evaluation_result.detail_codes)
        return GovernanceVerdict(
            status="blocked",
            summary=evaluation_result.summary,
            reason_codes=tuple(reason_codes) or ("evaluation_not_successful",),
        )

    if "qa_baseline_improved" in execution_result.detail_codes:
        return GovernanceVerdict(
            status="provisional",
            summary=(
                "Run improved on a broken baseline without introducing new failures, "
                "but evidence is not strong enough for full approval."
            ),
            reason_codes=("qa_baseline_improved",),
        )

    if "qa_approximated" in execution_result.detail_codes:
        return GovernanceVerdict(
            status="provisional",
            summary=(
                "Run passed local QA, but the executed command was only an approximation "
                "of the intended test invocation."
            ),
            reason_codes=("qa_approximated",),
        )

    return GovernanceVerdict(
        status="approved",
        summary="Required intake, execution, and evaluation evidence is present.",
        reason_codes=(),
    )
