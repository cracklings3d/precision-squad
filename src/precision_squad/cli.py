"""CLI entrypoints for precision-squad."""

from __future__ import annotations

import argparse
import importlib.resources
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, cast

from . import __version__
from .env import load_local_env
from .executor import DocsFirstExecutor
from .github_client import GitHubClientError, GitHubWriteClient
from .governance import apply_governance, evaluate_run
from .intake import is_docs_remediation_issue, load_issue_intake
from .models import (
    GitHubIssue,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    PostPublishReviewResult,
    PublishPlan,
    PublishResult,
    RunRecord,
    RunRequest,
)
from .post_publish_review import OpenCodePrReviewAgent, run_post_publish_review
from .publish_executor import execute_publish_plan
from .publishing import build_publish_plan
from .repair import (
    OpenCodeRepairAdapter,
    evaluate_docs_remediation_validation,
    merge_docs_remediation_execution_result,
    merge_execution_result,
    run_docs_remediation_repair,
    run_repair_qa_loop,
    synthesis_artifacts_ready,
)
from .run_store import RunStore


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
        default=".precision-squad/runs",
        help="Directory where run artifacts will be stored.",
    )
    issue_parser.add_argument(
        "--publish",
        action="store_true",
        help="Apply the publish plan to GitHub instead of only preparing it.",
    )
    issue_parser.add_argument(
        "--repo-path",
        required=True,
        help="Local filesystem path to the target repository checkout.",
    )
    issue_parser.add_argument(
        "--repair-agent",
        default="opencode",
        choices=("none", "opencode"),
        help="Repair agent adapter to run after the documented execution contract is prepared.",
    )
    issue_parser.add_argument(
        "--repair-model",
        default=None,
        help="Optional model override for the repair agent runtime.",
    )
    issue_parser.add_argument(
        "--review-model",
        default=None,
        help="Optional model override for post-publish review agents.",
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
        default=".precision-squad/runs",
        help="Directory where run artifacts are stored.",
    )
    publish_run_parser.add_argument(
        "--review-model",
        default=None,
        help="Optional model override for post-publish review agents.",
    )
    publish_run_parser.set_defaults(handler=_publish_run)

    install_skill_parser = subparsers.add_parser(
        "install-skill",
        help="Write a project-local SKILL.md for precision-squad workflows.",
    )
    install_skill_parser.add_argument(
        "--project-root",
        default=".",
        help="Project root where SKILL.md should be written.",
    )
    install_skill_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing SKILL.md file.",
    )
    install_skill_parser.set_defaults(handler=_install_skill)

    return parser


def _repair_issue(args: argparse.Namespace) -> int:
    intake = load_issue_intake(args.issue_ref)
    store = RunStore(Path(args.runs_dir))
    request = RunRequest(issue_ref=args.issue_ref, runs_dir=args.runs_dir)
    record = store.create_run(request, intake)
    run_dir = Path(record.run_dir).resolve()

    print(f"Issue: {intake.issue.reference}")
    print(f"Title: {intake.issue.title}")
    print(f"Run ID: {record.run_id}")
    print(f"Run Dir: {record.run_dir}")
    print(f"Classification: {intake.assessment.status}")

    if intake.assessment.reason_codes:
        print("Reasons:")
        for reason_code in intake.assessment.reason_codes:
            print(f"- {reason_code}")

    if intake.assessment.status == "blocked":
        verdict = apply_governance(intake, execution_result=None, evaluation_result=None)
        publish_plan = build_publish_plan(intake, record, verdict)
        store.write_governance_verdict(run_dir, verdict)
        store.write_publish_plan(run_dir, publish_plan)
        publish_result = execute_publish_plan(intake, publish_plan, publish=args.publish)
        store.write_publish_result(run_dir, publish_result)

        print(f"Governance: {verdict.status}")
        print(f"Governance Summary: {verdict.summary}")
        print(f"Publish Plan: {publish_plan.status}")
        print(f"Publish Result: {publish_result.status}")
        print(f"Publish Summary: {publish_result.summary}")
        return 3

    synthesis_result = DocsFirstExecutor(repo_path=Path(args.repo_path)).execute(
        intake, record, run_dir
    )
    repair_result = None
    baseline_qa_result = None
    qa_result = None
    execution_result = synthesis_result
    docs_remediation_issue = is_docs_remediation_issue(intake)
    if docs_remediation_issue and synthesis_artifacts_ready(synthesis_result):
        repair_adapter = None
        if args.repair_agent == "opencode":
            repair_adapter = OpenCodeRepairAdapter(model=args.repair_model)
        repair_result = run_docs_remediation_repair(
            repo_path=Path(args.repo_path),
            adapter=repair_adapter,
            intake=intake,
            run_record=record,
            run_dir=run_dir,
            contract_artifact_dir=(
                Path(synthesis_result.artifact_dir).resolve()
                if synthesis_result.artifact_dir
                else run_dir
            ),
        )
        store.write_repair_result(run_dir, repair_result)
        validation_result = None
        validation_scope_summary = None
        if repair_result.status == "completed" and repair_result.workspace_path:
            validation_run_dir = run_dir / "docs-remediation-validation"
            validation_repo_path = Path(repair_result.workspace_path).resolve() / "repo"
            validation_result = DocsFirstExecutor(repo_path=validation_repo_path).execute(
                intake,
                record,
                validation_run_dir,
            )
            validation_result, validation_scope_summary = evaluate_docs_remediation_validation(
                intake=intake,
                validation_result=validation_result,
            )
        execution_result = merge_docs_remediation_execution_result(
            synthesis_result,
            repair_result,
            validation_result,
            validation_scope_summary,
        )
    elif synthesis_result.status == "completed" and synthesis_artifacts_ready(synthesis_result):
        repair_adapter = None
        if args.repair_agent == "opencode":
            repair_adapter = OpenCodeRepairAdapter(model=args.repair_model)
        repair_result, baseline_qa_result, qa_result = run_repair_qa_loop(
            repo_path=Path(args.repo_path),
            adapter=repair_adapter,
            intake=intake,
            run_record=record,
            run_dir=run_dir,
            contract_artifact_dir=(
                Path(synthesis_result.artifact_dir).resolve()
                if synthesis_result.artifact_dir
                else run_dir
            ),
        )
        store.write_repair_result(run_dir, repair_result)
        if baseline_qa_result is not None:
            store.write_qa_result(run_dir, baseline_qa_result)
        if qa_result is not None:
            store.write_qa_result(run_dir, qa_result)
        execution_result = merge_execution_result(synthesis_result, repair_result, qa_result)
    store.write_execution_result(run_dir, execution_result)
    evaluation_result = evaluate_run(intake, execution_result)
    store.write_evaluation_result(run_dir, evaluation_result)
    verdict = apply_governance(intake, execution_result, evaluation_result)
    store.write_governance_verdict(run_dir, verdict)
    publish_plan = build_publish_plan(intake, record, verdict)
    store.write_publish_plan(run_dir, publish_plan)
    publish_result = execute_publish_plan(
        intake,
        publish_plan,
        publish=args.publish,
        run_dir=run_dir,
    )
    store.write_publish_result(run_dir, publish_result)
    post_publish_review_result = _run_post_publish_review_if_needed(
        intake=intake,
        run_record=record,
        run_dir=run_dir,
        publish_result=publish_result,
        review_model=args.review_model,
    )
    if post_publish_review_result is not None:
        store.write_post_publish_review_result(run_dir, post_publish_review_result)

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
    print(f"Governance: {verdict.status}")
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
    if verdict.status == "blocked":
        return 4
    if verdict.status == "provisional":
        return 5
    return 0


def _publish_run(args: argparse.Namespace) -> int:
    run_dir = (Path(args.runs_dir) / args.run_id).resolve()
    if not run_dir.exists():
        raise ValueError(f"Run directory not found: {run_dir}")

    intake = _read_issue_intake(run_dir)
    run_record = _read_run_record(run_dir)
    plan = _read_publish_plan(run_dir)
    existing_result = _read_publish_result(run_dir)
    existing_review_result = _read_post_publish_review_result(run_dir)
    result = existing_result

    if existing_result is not None and existing_result.status == "published":
        review_result = existing_review_result
        if review_result is None or review_result.status in {"failed_infra", "not_run"} or _post_publish_review_is_stale(intake, review_result):
            review_result = _run_post_publish_review_if_needed(
                intake=intake,
                run_record=run_record,
                run_dir=run_dir,
                publish_result=existing_result,
                review_model=args.review_model,
            )
            if review_result is not None:
                RunStore(Path(args.runs_dir)).write_post_publish_review_result(run_dir, review_result)
    else:
        result = execute_publish_plan(intake, plan, publish=True, run_dir=run_dir)
        RunStore(Path(args.runs_dir)).write_publish_result(run_dir, result)
        review_result = _run_post_publish_review_if_needed(
            intake=intake,
            run_record=run_record,
            run_dir=run_dir,
            publish_result=result,
            review_model=args.review_model,
        )
        if review_result is not None:
            RunStore(Path(args.runs_dir)).write_post_publish_review_result(run_dir, review_result)

    if result is None:
        raise ValueError(f"Run {args.run_id} is missing publish-result.json")

    print(f"Run ID: {args.run_id}")
    print(f"Run Dir: {run_dir}")
    print(f"Publish Plan: {plan.status}")
    print(f"Publish Result: {result.status}")
    print(f"Publish Summary: {result.summary}")
    if result.url:
        print(f"Publish URL: {result.url}")
    if review_result is not None:
        print(f"Post-Publish Review: {review_result.status}")
        print(f"Post-Publish Summary: {review_result.summary}")
        if review_result.issue_comment_url:
            print(f"Review Feedback URL: {review_result.issue_comment_url}")
    return 0


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
def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    load_local_env(Path(__file__).resolve().parent.parent.parent)
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0

    try:
        return handler(args)
    except (GitHubClientError, NotImplementedError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
