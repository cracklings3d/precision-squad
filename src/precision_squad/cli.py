"""CLI entrypoints for precision-squad."""

from __future__ import annotations

import argparse
import importlib.resources
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from . import __version__
from .config import (
    format_config_search_locations,
    load_command_config,
    merge_config_into_args,
)
from .coordinator import PublishRunParams, RepairIssueParams, RunCoordinator
from .env import load_local_env
from .executor import DocsFirstExecutor
from .github_client import GitHubClientError, GitHubWriteClient
from .intake import load_issue_intake
from .models import (
    ApprovedPlan,
    ExecutionResult,
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    NamedReference,
    PostPublishReviewResult,
    PublishPlan,
    PublishResult,
    QaResult,
    RepairResult,
    RunRecord,
)
from .post_publish_review import OpenCodePrReviewAgent, run_post_publish_review
from .publish_executor import execute_publish_plan
from .repair import (
    OpenCodeRepairAdapter,
    RepairAdapter,
    VercelAIRepairAdapter,
    evaluate_docs_remediation_validation,
    merge_docs_remediation_execution_result,
    merge_execution_result,
    run_docs_remediation_repair,
    run_repair_qa_loop,
    synthesis_artifacts_ready,
)

# Keep a local alias so tests can monkeypatch the shared executor class through this module.
_CLI_DOCS_FIRST_EXECUTOR = DocsFirstExecutor

_REPAIR_AGENT_CHOICES = ("none", "opencode", "vercel-ai")


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="precision-squad",
        description="Workflow control plane for docs-first issue repair.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    repair_parser = subparsers.add_parser(
        "repair",
        aliases=["run"],
        help="Repair a target GitHub issue through the workflow.",
    )
    repair_subparsers = repair_parser.add_subparsers(dest="repair_command")

    issue_parser = repair_subparsers.add_parser(
        "issue",
        help="Repair a GitHub issue reference.",
    )
    issue_parser.add_argument(
        "issue_ref",
        help="GitHub issue reference in the form owner/repo#number.",
    )
    issue_parser.add_argument(
        "--runs-dir",
        default=argparse.SUPPRESS,
        help="Directory where run artifacts will be stored.",
    )
    issue_parser.add_argument(
        "--publish",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Apply the publish plan to GitHub instead of only preparing it.",
    )
    issue_parser.add_argument(
        "--repo-path",
        default=argparse.SUPPRESS,
        help="Local filesystem path to the target repository checkout.",
    )
    issue_parser.add_argument(
        "--repair-agent",
        choices=_REPAIR_AGENT_CHOICES,
        default=argparse.SUPPRESS,
        help="Repair agent adapter to run after the documented execution contract is prepared.",
    )
    issue_parser.add_argument(
        "--repair-model",
        default=argparse.SUPPRESS,
        help="Optional model override for the repair agent runtime.",
    )
    issue_parser.add_argument(
        "--review-model",
        default=argparse.SUPPRESS,
        help="Optional model override for post-publish review agents.",
    )
    issue_parser.add_argument(
        "--retry-from",
        default=argparse.SUPPRESS,
        help="Existing run ID to retry from. Increments attempt counter.",
    )
    issue_parser.add_argument(
        "--approved-plan-path",
        default=argparse.SUPPRESS,
        help="Path to an approved-plan.json file to pass to the coordinator.",
    )
    issue_parser.set_defaults(handler=_repair_issue)

    publish_parser = subparsers.add_parser(
        "publish",
        help="Publish artifacts from an existing stored run without rerunning repair.",
    )
    publish_subparsers = publish_parser.add_subparsers(dest="publish_command")
    publish_run_parser = publish_subparsers.add_parser(
        "run",
        help="Publish the stored result for a run ID.",
    )
    publish_run_parser.add_argument("run_id", help="Existing run ID to publish.")
    publish_run_parser.add_argument(
        "--runs-dir",
        default=argparse.SUPPRESS,
        help="Directory where run artifacts are stored.",
    )
    publish_run_parser.add_argument(
        "--review-model",
        default=argparse.SUPPRESS,
        help="Optional model override for post-publish review agents.",
    )
    publish_run_parser.set_defaults(handler=_publish_run)

    install_skill_parser = subparsers.add_parser(
        "install-skill",
        help="Write a project-local SKILL.md for precision-squad workflows.",
    )
    install_skill_parser.add_argument(
        "--project-root",
        default=argparse.SUPPRESS,
        help="Project root where SKILL.md should be written.",
    )
    install_skill_parser.add_argument(
        "--force",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Overwrite an existing SKILL.md file.",
    )
    install_skill_parser.set_defaults(handler=_install_skill)

    return parser


def _repair_issue(args: argparse.Namespace) -> int:
    intake = load_issue_intake(args.issue_ref)
    approved_plan: ApprovedPlan | None = None
    if args.approved_plan_path:
        approved_plan = _load_approved_plan(Path(args.approved_plan_path), args.issue_ref)
    report = RunCoordinator().repair_issue(
        params=RepairIssueParams(
            issue_ref=args.issue_ref,
            runs_dir=Path(args.runs_dir),
            repo_path=Path(args.repo_path),
            publish=args.publish,
            repair_agent=args.repair_agent,
            repair_model=args.repair_model,
            review_model=args.review_model,
            retry_from=args.retry_from,
            approved_plan=approved_plan,
        ),
        intake=intake,
        dependencies=_CliRepairDependencies(),
    )
    record = report.run_record

    print(f"Issue: {intake.issue.reference}")
    print(f"Title: {intake.issue.title}")
    print(f"Run ID: {record.run_id}")
    print(f"Run Dir: {record.run_dir}")
    print(f"Classification: {intake.assessment.status}")

    if intake.assessment.reason_codes:
        print("Reasons:")
        for reason_code in intake.assessment.reason_codes:
            print(f"- {reason_code}")

    if report.execution_result is None:
        verdict = report.governance_verdict
        publish_plan = cast(PublishPlan, report.publish_plan)
        publish_result = cast(PublishResult, report.publish_result)
        print(f"Governance: {verdict.status if verdict else 'N/A'}")
        print(f"Governance Summary: {verdict.summary if verdict else 'N/A'}")
        print(f"Publish Plan: {publish_plan.status}")
        print(f"Publish Result: {publish_result.status}")
        print(f"Publish Summary: {publish_result.summary}")
        return report.exit_code

    execution_result = report.execution_result
    evaluation_result = cast(Any, report.evaluation_result)
    verdict = report.governance_verdict
    publish_plan = cast(PublishPlan, report.publish_plan)
    publish_result = cast(PublishResult, report.publish_result)
    repair_result = report.repair_result
    qa_result = report.qa_result
    post_publish_review_result = report.post_publish_review_result

    print(f"Summary: {intake.summary}")
    print(f"Problem: {intake.problem_statement}")
    print(f"Executor: {execution_result.executor_name}")
    print(f"Execution Status: {execution_result.status}")
    print(f"Execution Summary: {execution_result.summary}")
    if repair_result is not None:
        print(f"Repair Status: {repair_result.status}")
        print(f"Repair Summary: {repair_result.summary}")
    if qa_result is not None:
        print(f"QA Status: {qa_result.status}")
        print(f"QA Summary: {qa_result.summary}")
    print(f"Evaluation Status: {evaluation_result.status}")
    print(f"Governance: {verdict.status if verdict else 'N/A'}")
    print(f"Publish Plan: {publish_plan.status}")
    print(f"Publish Result: {publish_result.status}")
    print(f"Publish Summary: {publish_result.summary}")
    if publish_result.url:
        print(f"Publish URL: {publish_result.url}")
    if post_publish_review_result is not None:
        print(f"Post-Publish Review: {post_publish_review_result.status}")
        print(f"Post-Publish Summary: {post_publish_review_result.summary}")
        if post_publish_review_result.issue_comment_url:
            print(f"Review Feedback URL: {post_publish_review_result.issue_comment_url}")
    return report.exit_code


def _publish_run(args: argparse.Namespace) -> int:
    run_dir = (Path(args.runs_dir) / args.run_id).resolve()
    if not run_dir.exists():
        raise ValueError(f"Run directory not found: {run_dir}")

    report = RunCoordinator().publish_run(
        params=PublishRunParams(
            run_id=args.run_id,
            runs_dir=Path(args.runs_dir),
            review_model=args.review_model,
        ),
        intake=_read_issue_intake(run_dir),
        run_record=_read_run_record(run_dir),
        publish_plan=_read_publish_plan(run_dir),
        existing_result=_read_publish_result(run_dir),
        existing_review_result=_read_post_publish_review_result(run_dir),
        dependencies=_CliPublishDependencies(),
    )

    print(f"Run ID: {args.run_id}")
    print(f"Run Dir: {report.run_dir}")
    print(f"Publish Plan: {report.publish_plan.status}")
    print(f"Publish Result: {report.publish_result.status}")
    print(f"Publish Summary: {report.publish_result.summary}")
    if report.publish_result.url:
        print(f"Publish URL: {report.publish_result.url}")
    if report.post_publish_review_result is not None:
        print(f"Post-Publish Review: {report.post_publish_review_result.status}")
        print(f"Post-Publish Summary: {report.post_publish_review_result.summary}")
        if report.post_publish_review_result.issue_comment_url:
            print(f"Review Feedback URL: {report.post_publish_review_result.issue_comment_url}")
    return 0


class _CliRepairDependencies:
    def create_repair_adapter(
        self, *, repair_agent: str, repair_model: str | None
    ) -> RepairAdapter | None:
        if repair_agent == "opencode":
            return OpenCodeRepairAdapter(model=repair_model)
        if repair_agent == "vercel-ai":
            return VercelAIRepairAdapter(model=repair_model)
        return None

    def run_repair_qa_loop(
        self,
        *,
        repo_path: Path,
        adapter: RepairAdapter | None,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
    ) -> tuple[RepairResult, QaResult, QaResult]:
        return run_repair_qa_loop(
            repo_path=repo_path,
            adapter=adapter,
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
        )

    def run_docs_remediation_repair(
        self,
        *,
        repo_path: Path,
        adapter: RepairAdapter | None,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        contract_artifact_dir: Path,
    ) -> RepairResult:
        return run_docs_remediation_repair(
            repo_path=repo_path,
            adapter=adapter,
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            contract_artifact_dir=contract_artifact_dir,
        )

    def evaluate_docs_remediation_validation(
        self,
        *,
        intake: IssueIntake,
        validation_result: ExecutionResult,
    ) -> tuple[ExecutionResult, str | None]:
        return evaluate_docs_remediation_validation(
            intake=intake,
            validation_result=validation_result,
        )

    def merge_docs_remediation_execution_result(
        self,
        synthesis_result: ExecutionResult,
        repair_result: RepairResult,
        validation_result: ExecutionResult | None,
        validation_scope_summary: str | None = None,
    ) -> ExecutionResult:
        return merge_docs_remediation_execution_result(
            synthesis_result,
            repair_result,
            validation_result,
            validation_scope_summary,
        )

    def merge_execution_result(
        self,
        synthesis_result: ExecutionResult,
        repair_result: RepairResult,
        qa_result: QaResult | None = None,
    ) -> ExecutionResult:
        return merge_execution_result(synthesis_result, repair_result, qa_result)

    def synthesis_artifacts_ready(self, execution_result: ExecutionResult) -> bool:
        return synthesis_artifacts_ready(execution_result)

    def execute_publish_plan(
        self,
        intake: IssueIntake,
        plan: PublishPlan,
        *,
        publish: bool,
        run_dir: Path | None = None,
    ) -> PublishResult:
        return execute_publish_plan(intake, plan, publish=publish, run_dir=run_dir)

    def run_post_publish_review_if_needed(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        publish_result: PublishResult,
        review_model: str | None,
    ) -> PostPublishReviewResult | None:
        return _run_post_publish_review_if_needed(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            publish_result=publish_result,
            review_model=review_model,
        )


class _CliPublishDependencies:
    def execute_publish_plan(
        self,
        intake: IssueIntake,
        plan: PublishPlan,
        *,
        publish: bool,
        run_dir: Path | None = None,
    ) -> PublishResult:
        return execute_publish_plan(intake, plan, publish=publish, run_dir=run_dir)

    def run_post_publish_review_if_needed(
        self,
        *,
        intake: IssueIntake,
        run_record: RunRecord,
        run_dir: Path,
        publish_result: PublishResult,
        review_model: str | None,
    ) -> PostPublishReviewResult | None:
        return _run_post_publish_review_if_needed(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            publish_result=publish_result,
            review_model=review_model,
        )

    def post_publish_review_is_stale(
        self, intake: IssueIntake, review_result: PostPublishReviewResult
    ) -> bool:
        return _post_publish_review_is_stale(intake, review_result)


def _install_skill(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        raise ValueError(f"Project root not found: {project_root}")
    if not project_root.is_dir():
        raise ValueError(f"Project root is not a directory: {project_root}")

    target_path = project_root / "SKILL.md"
    if target_path.exists() and not args.force:
        raise ValueError(
            f"SKILL.md already exists at {target_path}. Re-run with --force to overwrite it."
        )

    template = _load_project_skill_template()
    target_path.write_text(template, encoding="utf-8")

    print(f"Installed skill: {target_path}")
    return 0


def _read_issue_intake(run_dir: Path) -> IssueIntake:
    payload = _read_json(run_dir / "issue-intake.json")
    issue_payload = _as_mapping(payload["issue"])
    reference_payload = _as_mapping(issue_payload["reference"])
    assessment_payload = _as_mapping(payload["assessment"])
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference(
                owner=_as_str(reference_payload["owner"]),
                repo=_as_str(reference_payload["repo"]),
                number=_as_int(reference_payload["number"]),
            ),
            title=_as_str(issue_payload["title"]),
            body=_as_str(issue_payload["body"]),
            labels=_as_str_tuple(issue_payload["labels"]),
            html_url=_as_str(issue_payload["html_url"]),
            comments=_as_str_tuple(issue_payload.get("comments", [])),
        ),
        summary=_as_str(payload["summary"]),
        problem_statement=_as_str(payload["problem_statement"]),
        assessment=IssueAssessment(
            status=_as_issue_assessment_status(assessment_payload["status"]),
            reason_codes=_as_str_tuple(assessment_payload["reason_codes"]),
        ),
    )


def _read_publish_plan(run_dir: Path) -> PublishPlan:
    payload = _read_json(run_dir / "publish-plan.json")
    return PublishPlan(
        status=_as_publish_plan_status(payload["status"]),
        title=_as_str(payload["title"]),
        body=_as_str(payload["body"]),
        reason_codes=_as_str_tuple(payload["reason_codes"]),
        branch_name=_as_optional_str(payload.get("branch_name")),
        pull_request_url=_as_optional_str(payload.get("pull_request_url")),
        pull_number=_as_optional_int(payload.get("pull_number")),
    )


def _read_publish_result(run_dir: Path) -> PublishResult | None:
    path = run_dir / "publish-result.json"
    if not path.exists():
        return None
    payload = _read_json(path)
    return PublishResult(
        status=_as_publish_result_status(payload["status"]),
        target=_as_publish_plan_status(payload["target"]),
        summary=_as_str(payload["summary"]),
        url=_as_optional_str(payload.get("url")),
        branch_name=_as_optional_str(payload.get("branch_name")),
        pull_number=_as_optional_int(payload.get("pull_number")),
    )


def _read_run_record(run_dir: Path) -> RunRecord:
    payload = _read_json(run_dir / "run-record.json")
    return RunRecord(
        run_id=_as_str(payload["run_id"]),
        issue_ref=_as_str(payload["issue_ref"]),
        status=_as_run_record_status(payload["status"]),
        created_at=_as_str(payload["created_at"]),
        updated_at=_as_str(payload["updated_at"]),
        run_dir=_as_str(payload["run_dir"]),
        attempt=_as_int(payload.get("attempt", 1)),
    )


def _read_post_publish_review_result(run_dir: Path) -> PostPublishReviewResult | None:
    path = run_dir / "post-publish-review-result.json"
    if not path.exists():
        return None
    payload = _read_json(path)
    return PostPublishReviewResult(
        status=_as_post_publish_review_status(payload["status"]),
        summary=_as_str(payload["summary"]),
        pull_request_url=_as_optional_str(payload.get("pull_request_url")),
        pull_number=_as_optional_int(payload.get("pull_number")),
        pull_head_sha=_as_optional_str(payload.get("pull_head_sha")),
        reviewer_status=_as_review_agent_status(payload["reviewer_status"]),
        reviewer_summary=_as_str(payload["reviewer_summary"]),
        reviewer_feedback=_as_str_tuple(payload.get("reviewer_feedback", [])),
        architect_status=_as_review_agent_status(payload["architect_status"]),
        architect_summary=_as_str(payload["architect_summary"]),
        architect_feedback=_as_str_tuple(payload.get("architect_feedback", [])),
        issue_comment_url=_as_optional_str(payload.get("issue_comment_url")),
        issue_reopened=_as_bool(payload.get("issue_reopened", False)),
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return cast(dict[str, Any], payload)


def _load_project_skill_template() -> str:
    template = importlib.resources.files("precision_squad.data").joinpath(
        "project_skill_template.md"
    )
    return template.read_text(encoding="utf-8")


def _as_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return cast(dict[str, Any], value)


def _as_str(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected string value")
    return value


def _as_int(value: Any) -> int:
    if not isinstance(value, int):
        raise ValueError("Expected integer value")
    return value


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Expected list of strings")
    return tuple(value)


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return _as_str(value)


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return _as_int(value)


def _as_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Expected boolean value")
    return value


def _load_approved_plan(path: Path, issue_ref: str) -> ApprovedPlan:
    """Load and validate an ApprovedPlan from a JSON file."""
    payload = _read_json(path)
    if "issue_ref" not in payload:
        raise ValueError("Approved plan is missing required field 'issue_ref'")
    plan_issue_ref = _as_str(payload.get("issue_ref"))
    if plan_issue_ref != issue_ref:
        raise ValueError(
            f"Approved plan issue_ref '{plan_issue_ref}' does not match CLI issue_ref '{issue_ref}'"
        )
    plan_summary = _as_str(payload.get("plan_summary"))
    if not plan_summary.strip():
        raise ValueError("Approved plan is missing a non-empty 'plan_summary'")
    implementation_steps_raw = payload.get("implementation_steps", [])
    if not isinstance(implementation_steps_raw, list):
        raise ValueError("Expected 'implementation_steps' to be a list")
    implementation_steps = tuple(str(step) for step in implementation_steps_raw)
    if not implementation_steps:
        raise ValueError("Approved plan has no implementation steps")
    named_references_raw = payload.get("named_references", [])
    if not isinstance(named_references_raw, list):
        raise ValueError("Expected 'named_references' to be a list")
    named_refs: list[NamedReference] = []
    allowed_types = {"file", "interface", "symbol", "example"}
    for ref in named_references_raw:
        if isinstance(ref, dict):
            name = str(ref.get("name", ""))
            if not name:
                raise ValueError("Named reference has empty name")
            ref_type = ref.get("reference_type", "file")
            if ref_type not in allowed_types:
                raise ValueError(
                    "Named reference has invalid reference_type "
                    f"'{ref_type}'; expected one of {allowed_types}"
                )
            named_refs.append(
                NamedReference(
                    name=name,
                    reference_type=ref_type,
                    description=str(ref.get("description", "")),
                )
            )
        else:
            named_refs.append(NamedReference(name=str(ref)))
    return ApprovedPlan(
        issue_ref=plan_issue_ref,
        plan_summary=plan_summary,
        implementation_steps=implementation_steps,
        named_references=tuple(named_refs),
        retrieval_surface_summary=str(payload.get("retrieval_surface_summary", "")),
        approved=bool(payload.get("approved", True)),
    )


def _as_issue_assessment_status(value: Any) -> Literal["runnable", "blocked"]:
    text = _as_str(value)
    if text == "runnable":
        return "runnable"
    if text == "blocked":
        return "blocked"
    raise ValueError("Expected issue assessment status")


def _as_publish_plan_status(
    value: Any,
) -> Literal["draft_pr", "issue_comment", "follow_up_issue"]:
    text = _as_str(value)
    if text == "draft_pr":
        return "draft_pr"
    if text == "issue_comment":
        return "issue_comment"
    if text == "follow_up_issue":
        return "follow_up_issue"
    raise ValueError("Expected publish plan status")


def _as_publish_result_status(value: Any) -> Literal["dry_run", "published"]:
    text = _as_str(value)
    if text == "dry_run":
        return "dry_run"
    if text == "published":
        return "published"
    raise ValueError("Expected publish result status")


def _as_run_record_status(value: Any) -> Literal["intake_complete", "blocked", "runnable"]:
    text = _as_str(value)
    if text == "intake_complete":
        return "intake_complete"
    if text == "blocked":
        return "blocked"
    if text == "runnable":
        return "runnable"
    raise ValueError("Expected run record status")


def _as_review_agent_status(
    value: Any,
) -> Literal["approved", "rejected", "failed_infra", "not_run"]:
    text = _as_str(value)
    if text == "approved":
        return "approved"
    if text == "rejected":
        return "rejected"
    if text == "failed_infra":
        return "failed_infra"
    if text == "not_run":
        return "not_run"
    raise ValueError("Expected review agent status")


def _as_post_publish_review_status(
    value: Any,
) -> Literal["approved", "rejected", "failed_infra", "not_run"]:
    return _as_review_agent_status(value)


def _run_post_publish_review_if_needed(
    *,
    intake: IssueIntake,
    run_record: RunRecord,
    run_dir: Path,
    publish_result: PublishResult,
    review_model: str | None,
) -> PostPublishReviewResult | None:
    if (
        publish_result.status != "published"
        or publish_result.target != "draft_pr"
        or not publish_result.url
    ):
        return None

    return run_post_publish_review(
        intake=intake,
        run_record=run_record,
        run_dir=run_dir,
        pull_request_url=publish_result.url,
        reviewer=OpenCodePrReviewAgent(role="reviewer", model=review_model),
        architect=OpenCodePrReviewAgent(role="architect", model=review_model),
    )


def _post_publish_review_is_stale(
    intake: IssueIntake, review_result: PostPublishReviewResult
) -> bool:
    if review_result.pull_number is None:
        return False
    try:
        head_sha = GitHubWriteClient.from_env().get_pull_request_head_sha(
            intake.issue.reference.owner,
            intake.issue.reference.repo,
            review_result.pull_number,
        )
    except GitHubClientError:
        return False
    if head_sha is None:
        return False
    return head_sha != review_result.pull_head_sha


@dataclass(frozen=True)
class _CommandConfigSpec:
    table: tuple[str, ...]
    supported_keys: frozenset[str]
    defaults: dict[str, Any]
    validate: Callable[[dict[str, Any]], None]
    discovery_root: Callable[[argparse.Namespace], Path]


def _validate_repair_issue_args(args: dict[str, Any]) -> None:
    _require_config_value(args, "repo_path")
    args["runs_dir"] = _config_str(args.get("runs_dir"), key="runs_dir")
    args["repo_path"] = _config_str(args.get("repo_path"), key="repo_path")
    args["publish"] = _coerce_bool(args.get("publish"), key="publish")
    args["repair_agent"] = _validate_repair_agent(args.get("repair_agent"))
    _normalize_optional_path_arg(args, "approved_plan_path")
    _normalize_optional_str_arg(args, "repair_model")
    _normalize_optional_str_arg(args, "review_model")


def _validate_publish_run_args(args: dict[str, Any]) -> None:
    args["runs_dir"] = _config_str(args.get("runs_dir"), key="runs_dir")
    _normalize_optional_str_arg(args, "review_model")


def _validate_install_skill_args(args: dict[str, Any]) -> None:
    args["project_root"] = _config_str(args.get("project_root"), key="project_root")
    args["force"] = _coerce_bool(args.get("force"), key="force")


def _repair_issue_config_root(args: argparse.Namespace) -> Path:
    repo_path = getattr(args, "repo_path", argparse.SUPPRESS)
    if repo_path is argparse.SUPPRESS:
        return Path.cwd()
    return Path(repo_path)


def _publish_run_config_root(args: argparse.Namespace) -> Path:
    del args
    return Path.cwd()


def _install_skill_config_root(args: argparse.Namespace) -> Path:
    project_root = getattr(args, "project_root", argparse.SUPPRESS)
    if project_root is argparse.SUPPRESS:
        return Path.cwd()
    return Path(project_root)


_COMMAND_CONFIG_SPECS: dict[Callable[[argparse.Namespace], int], _CommandConfigSpec] = {
    _repair_issue: _CommandConfigSpec(
        table=("repair", "issue"),
        supported_keys=frozenset(
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
        defaults={
            "runs_dir": ".precision-squad/runs",
            "publish": False,
            "repair_agent": "opencode",
            "repair_model": None,
            "review_model": None,
            "retry_from": None,
            "approved_plan_path": None,
        },
        validate=_validate_repair_issue_args,
        discovery_root=_repair_issue_config_root,
    ),
    _publish_run: _CommandConfigSpec(
        table=("publish", "run"),
        supported_keys=frozenset({"runs_dir", "review_model"}),
        defaults={"runs_dir": ".precision-squad/runs", "review_model": None},
        validate=_validate_publish_run_args,
        discovery_root=_publish_run_config_root,
    ),
    _install_skill: _CommandConfigSpec(
        table=("install-skill",),
        supported_keys=frozenset({"project_root", "force"}),
        defaults={"project_root": ".", "force": False},
        validate=_validate_install_skill_args,
        discovery_root=_install_skill_config_root,
    ),
}


def _resolve_cli_args(
    parser: argparse.ArgumentParser, argv: Sequence[str] | None
) -> argparse.Namespace:
    parsed_args = parser.parse_args(list(argv) if argv is not None else None)
    handler = getattr(parsed_args, "handler", None)
    if handler is None:
        return parsed_args

    spec = _COMMAND_CONFIG_SPECS.get(handler)
    if spec is None:
        return parsed_args

    args_dict = vars(parsed_args)
    for key in spec.supported_keys:
        args_dict.setdefault(key, argparse.SUPPRESS)
    config = load_command_config(
        start_dir=spec.discovery_root(parsed_args),
        table=spec.table,
        supported_tables={
            command_spec.table: command_spec.supported_keys
            for command_spec in _COMMAND_CONFIG_SPECS.values()
        },
    )
    merged = merge_config_into_args(config, args_dict)
    resolved = _apply_config_defaults(merged, spec)
    _validate_resolved_args(resolved, spec)
    return argparse.Namespace(**resolved)


def _apply_config_defaults(args: dict[str, Any], spec: _CommandConfigSpec) -> dict[str, Any]:
    resolved = dict(args)
    for key, value in spec.defaults.items():
        if resolved.get(key, argparse.SUPPRESS) is argparse.SUPPRESS:
            resolved[key] = value
    return resolved


def _validate_resolved_args(args: dict[str, Any], spec: _CommandConfigSpec) -> None:
    spec.validate(args)


def _arg_reference(key: str) -> str:
    return f"'{key}' (--{key.replace('_', '-')})"


def _require_config_value(args: dict[str, Any], key: str) -> None:
    value = args.get(key, argparse.SUPPRESS)
    if value is argparse.SUPPRESS or value is None:
        raise ValueError(
            f"Missing required value for {_arg_reference(key)}. "
            f"Provide --{key.replace('_', '-')} or set it in a precision-squad config file "
            f"at {format_config_search_locations()} under the active command's discovery root."
        )
    if isinstance(value, str) and not value.strip():
        raise ValueError(
            f"Missing required value for {_arg_reference(key)}. "
            f"Provide --{key.replace('_', '-')} or set it in a precision-squad config file "
            f"at {format_config_search_locations()} under the active command's discovery root."
        )


def _normalize_optional_str_arg(args: dict[str, Any], key: str) -> None:
    value = args.get(key)
    if value is None:
        return
    args[key] = _config_str(value, key=key)


def _normalize_optional_path_arg(args: dict[str, Any], key: str) -> None:
    value = args.get(key)
    if value is None:
        return
    args[key] = _config_str(value, key=key)


def _config_str(value: Any, *, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid value for {_arg_reference(key)}: expected a non-empty string")
    return value


def _validate_repair_agent(value: Any) -> str:
    repair_agent = _config_str(value, key="repair_agent")
    if repair_agent not in _REPAIR_AGENT_CHOICES:
        expected = ", ".join(_REPAIR_AGENT_CHOICES)
        raise ValueError(
            f"Invalid value for {_arg_reference('repair_agent')}: "
            f"{repair_agent!r}. Expected one of: {expected}"
        )
    return repair_agent


def _coerce_bool(value: Any, *, key: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"Invalid value for {_arg_reference(key)}: expected a boolean")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    load_local_env(Path(__file__).resolve().parent.parent.parent)
    parser = build_parser()
    try:
        args = _resolve_cli_args(parser, argv)
        handler = getattr(args, "handler", None)
        if handler is None:
            parser.print_help()
            return 0
        return handler(args)
    except (GitHubClientError, NotImplementedError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
