"""Tests for post-publish PR review behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

import pytest

from precision_squad.models import (
    GitHubIssue,
    ImplReviewResult,
    IssueAssessment,
    IssueIntake,
    IssueReference,
    ReviewAgentResult,
    RunRecord,
)
from precision_squad.post_publish_review import (
    OpenCodePrReviewAgent,
    ReviewRunner,
    _build_review_prompt,
    _parse_review_output,
    mirror_impl_review_to_post_publish,
    run_impl_review,
    run_post_publish_review,
)
from precision_squad.run_store import RunStore


def _intake() -> IssueIntake:
    return IssueIntake(
        issue=GitHubIssue(
            reference=IssueReference("cracklings3d", "markdown-pdf-renderer", 9),
            title="[Enhancement] Add --version flag to CLI",
            body="## Description\nAdd a version flag.",
            labels=("enhancement",),
            html_url="https://github.com/cracklings3d/markdown-pdf-renderer/issues/9",
        ),
        summary="Add --version flag to CLI",
        problem_statement="Add a version flag.",
        assessment=IssueAssessment(status="runnable", reason_codes=()),
    )


def _record(tmp_path: Path) -> RunRecord:
    return RunRecord(
        run_id="run-123",
        issue_ref="cracklings3d/markdown-pdf-renderer#9",
        status="runnable",
        created_at="2026-04-27T00:00:00Z",
        updated_at="2026-04-27T00:00:00Z",
        run_dir=str(tmp_path / "run-123"),
    )


def _write_approved_plan(run_dir: Path) -> None:
    (run_dir / "approved-plan.json").write_text(
        json.dumps(
            {
                "issue_ref": "cracklings3d/markdown-pdf-renderer#9",
                "plan_summary": "Review the implementation against the approved plan.",
                "implementation_steps": ["Inspect the diff"],
                "named_references": [],
                "retrieval_surface_summary": "src/",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )


def _review_result(
    *,
    role: Literal["reviewer", "architect"],
    status: Literal["approved", "rejected", "failed_infra", "not_run"],
    summary: str,
    feedback: tuple[str, ...] = (),
    plan_alignment: Literal[
        "aligned", "justified_deviation", "unjustified_deviation", "non_material_detail"
    ] | None = "aligned",
    plan_alignment_findings: tuple[str, ...] = (),
    justification_findings: tuple[str, ...] = (),
) -> ReviewAgentResult:
    return ReviewAgentResult(
        role=role,
        status=status,
        summary=summary,
        feedback=feedback,
        plan_alignment=plan_alignment,
        plan_alignment_findings=plan_alignment_findings,
        justification_findings=justification_findings,
    )


def _stub_agent(result: ReviewAgentResult) -> ReviewRunner:
    class StubAgent:
        def review(self, **kwargs) -> ReviewAgentResult:
            del kwargs
            return result

    return cast(ReviewRunner, StubAgent())


def _valid_agent_payload(status: str = "approved") -> str:
    return json.dumps(
        {
            "status": status,
            "summary": "ok",
            "feedback": [],
            "plan_alignment": "aligned",
            "plan_alignment_findings": [],
            "justification_findings": [],
        }
    )


def test_parse_review_output_requires_expanded_plan_alignment_fields() -> None:
    assert (
        _parse_review_output(
            [
                {
                    "type": "text",
                    "part": {
                        "text": json.dumps(
                            {
                                "status": "approved",
                                "summary": "ok",
                                "feedback": [],
                            }
                        )
                    },
                }
            ]
        )
        is None
    )


def test_parse_review_output_accepts_expanded_payload_with_prose_prefix() -> None:
    payload = _parse_review_output(
        [
            {
                "type": "text",
                "part": {
                    "text": (
                        "The implementation is solid.\n\n"
                        '{"status":"rejected","summary":"needs fixes",'
                        '"feedback":["adjust review contract"],'
                        '"plan_alignment":"unjustified_deviation",'
                        '"plan_alignment_findings":["Changed behavior outside approved plan"],'
                        '"justification_findings":["No surfaced justification for the change"]}'
                    )
                },
            }
        ]
    )

    assert payload is not None
    assert payload["status"] == "rejected"
    assert payload["plan_alignment"] == "unjustified_deviation"
    assert payload["plan_alignment_findings"] == ("Changed behavior outside approved plan",)
    assert payload["justification_findings"] == ("No surfaced justification for the change",)


def test_opencode_pr_review_agent_reads_expanded_json_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_approved_plan(tmp_path)

    def fake_run(command, cwd, capture_output, text):
        del command, cwd, capture_output, text

        class _Completed:
            returncode = 0
            stdout = '{"type":"text","part":{"text":' + json.dumps(_valid_agent_payload()) + "}}\n"
            stderr = ""

        return _Completed()

    monkeypatch.setattr("precision_squad.post_publish_review.subprocess.run", fake_run)
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "## Design Decisions\n```json\n[]\n```\n",
    )

    result = OpenCodePrReviewAgent(role="reviewer").review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
    )

    assert result.status == "approved"
    assert result.plan_alignment == "aligned"
    assert result.plan_alignment_findings == ()
    assert result.justification_findings == ()


def test_build_review_prompt_describes_expanded_review_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_approved_plan(tmp_path)
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "## Design Decisions\n```json\n[]\n```\n",
    )

    prompt = _build_review_prompt(
        role="reviewer",
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
    )

    assert '"plan_alignment"' in prompt
    assert '"plan_alignment_findings"' in prompt
    assert '"justification_findings"' in prompt
    assert "Use only the surfaced PR-body ## Design Decisions section as justification evidence." in prompt


def test_run_post_publish_review_preserves_two_agent_approval_rule(tmp_path: Path) -> None:
    _write_approved_plan(tmp_path)

    class StubWriter:
        def get_pull_request_head_sha(self, owner: str, repo: str, pull_number: int):
            del owner, repo, pull_number
            return "head-sha"

        def create_issue_comment(self, reference, body):
            del reference, body
            return "comment-url"

        def reopen_issue(self, reference):
            del reference

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "## Design Decisions\n```json\n[]\n```\n",
    )
    try:
        approved = run_post_publish_review(
            intake=_intake(),
            run_record=_record(tmp_path),
            run_dir=tmp_path,
            pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            reviewer=_stub_agent(
                _review_result(role="reviewer", status="approved", summary="Reviewer approves.")
            ),
            architect=_stub_agent(
                _review_result(role="architect", status="approved", summary="Architect approves.")
            ),
        )
        rejected = run_post_publish_review(
            intake=_intake(),
            run_record=_record(tmp_path),
            run_dir=tmp_path,
            pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            reviewer=_stub_agent(
                _review_result(role="reviewer", status="approved", summary="Reviewer approves.")
            ),
            architect=_stub_agent(
                _review_result(
                    role="architect",
                    status="rejected",
                    summary="Architect rejects.",
                    plan_alignment="unjustified_deviation",
                    plan_alignment_findings=("Architect found scope drift.",),
                )
            ),
        )
        failed_infra = run_post_publish_review(
            intake=_intake(),
            run_record=_record(tmp_path),
            run_dir=tmp_path,
            pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            reviewer=_stub_agent(
                _review_result(role="reviewer", status="approved", summary="Reviewer approves.")
            ),
            architect=_stub_agent(
                _review_result(
                    role="architect",
                    status="failed_infra",
                    summary="Architect crashed.",
                    plan_alignment=None,
                )
            ),
        )
    finally:
        monkeypatch.undo()

    assert approved.status == "approved"
    assert rejected.status == "rejected"
    assert failed_infra.status == "failed_infra"


def test_run_post_publish_review_persists_per_agent_and_aggregated_evidence(tmp_path: Path) -> None:
    _write_approved_plan(tmp_path)
    comments: list[str] = []

    class StubWriter:
        def get_pull_request_head_sha(self, owner: str, repo: str, pull_number: int):
            del owner, repo, pull_number
            return "head-sha"

        def create_issue_comment(self, reference, body):
            del reference
            comments.append(body)
            return "comment-url"

        def reopen_issue(self, reference):
            del reference

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "## Design Decisions\n```json\n[]\n```\n",
    )
    try:
        result = run_post_publish_review(
            intake=_intake(),
            run_record=_record(tmp_path),
            run_dir=tmp_path,
            pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            reviewer=_stub_agent(
                _review_result(
                    role="reviewer",
                    status="rejected",
                    summary="Reviewer found an issue.",
                    feedback=("Fix review handling.",),
                    plan_alignment="unjustified_deviation",
                    plan_alignment_findings=("Changed review output contract.",),
                    justification_findings=("No surfaced justification for contract change.",),
                )
            ),
            architect=_stub_agent(
                _review_result(
                    role="architect",
                    status="approved",
                    summary="Structure looks fine.",
                    plan_alignment="aligned",
                    plan_alignment_findings=("Matches approved structure.",),
                    justification_findings=("Surfaced design decisions are consistent.",),
                )
            ),
        )
    finally:
        monkeypatch.undo()

    assert result.per_agent_evidence is not None
    assert result.per_agent_evidence.reviewer.role == "reviewer"
    assert result.per_agent_evidence.reviewer.plan_alignment == "unjustified_deviation"
    assert result.per_agent_evidence.architect.role == "architect"
    assert result.aggregated_plan_alignment.classification == "unjustified_deviation"
    assert result.aggregated_plan_alignment.plan_alignment_findings == (
        "Changed review output contract.",
        "Matches approved structure.",
    )
    assert result.aggregated_plan_alignment.justification_findings == (
        "No surfaced justification for contract change.",
        "Surfaced design decisions are consistent.",
    )

    store = RunStore(tmp_path)
    store.write_post_publish_review_result(tmp_path, result)
    payload = json.loads((tmp_path / "post-publish-review-result.json").read_text(encoding="utf-8"))
    assert payload["reviewer_status"] == "rejected"
    assert payload["architect_status"] == "approved"
    assert payload["per_agent_evidence"]["reviewer"]["plan_alignment"] == "unjustified_deviation"
    assert payload["per_agent_evidence"]["architect"]["plan_alignment"] == "aligned"
    assert payload["aggregated_plan_alignment"]["classification"] == "unjustified_deviation"


@pytest.mark.parametrize(
    ("reviewer_alignment", "architect_alignment", "expected"),
    [
        ("aligned", "aligned", "aligned"),
        ("non_material_detail", "aligned", "non_material_detail"),
        ("aligned", "justified_deviation", "justified_deviation"),
        ("justified_deviation", "unjustified_deviation", "unjustified_deviation"),
    ],
)
def test_run_post_publish_review_aggregates_plan_alignment_by_precedence(
    tmp_path: Path,
    reviewer_alignment: str,
    architect_alignment: str,
    expected: str,
) -> None:
    _write_approved_plan(tmp_path)

    class StubWriter:
        def get_pull_request_head_sha(self, owner: str, repo: str, pull_number: int):
            del owner, repo, pull_number
            return "head-sha"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "## Design Decisions\n```json\n[]\n```\n",
    )
    try:
        result = run_post_publish_review(
            intake=_intake(),
            run_record=_record(tmp_path),
            run_dir=tmp_path,
            pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
            reviewer=_stub_agent(
                _review_result(
                    role="reviewer",
                    status="approved",
                    summary="Reviewer approves.",
                    plan_alignment=cast(
                        Literal[
                            "aligned",
                            "justified_deviation",
                            "unjustified_deviation",
                            "non_material_detail",
                        ],
                        reviewer_alignment,
                    ),
                )
            ),
            architect=_stub_agent(
                _review_result(
                    role="architect",
                    status="approved",
                    summary="Architect approves.",
                    plan_alignment=cast(
                        Literal[
                            "aligned",
                            "justified_deviation",
                            "unjustified_deviation",
                            "non_material_detail",
                        ],
                        architect_alignment,
                    ),
                )
            ),
        )
    finally:
        monkeypatch.undo()

    assert result.aggregated_plan_alignment.classification == expected


def test_run_post_publish_review_rejection_comment_stays_bounded_but_concrete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_approved_plan(tmp_path)
    comments: list[str] = []

    class StubWriter:
        def get_pull_request_head_sha(self, owner: str, repo: str, pull_number: int):
            del owner, repo, pull_number
            return "head-sha"

        def create_issue_comment(self, reference, body):
            del reference
            comments.append(body)
            return "https://github.com/cracklings3d/markdown-pdf-renderer/issues/9#issuecomment-2"

        def reopen_issue(self, reference):
            del reference

    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "## Design Decisions\n```json\n[]\n```\n",
    )

    result = run_post_publish_review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
        reviewer=_stub_agent(
            _review_result(
                role="reviewer",
                status="rejected",
                summary="Reviewer found an issue.",
                feedback=("Fix review handling.",),
                plan_alignment="unjustified_deviation",
                plan_alignment_findings=("Changed review output contract.",),
                justification_findings=("No surfaced justification for contract change.",),
            )
        ),
        architect=_stub_agent(
            _review_result(
                role="architect",
                status="rejected",
                summary="Architect found an issue.",
                feedback=("Restore approved boundary.",),
                plan_alignment="justified_deviation",
                plan_alignment_findings=("Minor structural change observed.",),
                justification_findings=("Surfaced justification conflicts with implementation.",),
            )
        ),
    )

    assert result.status == "rejected"
    assert comments
    comment = comments[0]
    assert "Reviewer verdict: `rejected`" in comment
    assert "Architect verdict: `rejected`" in comment
    assert "Plan alignment: `unjustified_deviation`" in comment
    assert "Plan alignment: `justified_deviation`" in comment
    assert "Changed review output contract." in comment
    assert "Surfaced justification conflicts with implementation." in comment
    assert "aggregated_plan_alignment" not in comment
    assert "stdout_path" not in comment


def test_run_impl_review_returns_approved_for_same_run_same_issue_published_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_approved_plan(tmp_path)
    comments: list[str] = []

    class StubWriter:
        def get_pull_request(self, owner: str, repo: str, pull_number: int):
            del owner, repo
            return {
                "number": pull_number,
                "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "head": {"sha": "head-sha"},
                "base": {"repo": {"name": "markdown-pdf-renderer", "owner": {"login": "cracklings3d"}}},
                "body": "- Run ID: `run-123`\n- Issue: `cracklings3d/markdown-pdf-renderer#9`\n",
            }

        def create_issue_comment(self, reference, body):
            del reference
            comments.append(body)
            return "comment-url"

        def reopen_issue(self, reference):
            del reference

    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "- Run ID: `run-123`\n- Issue: `cracklings3d/markdown-pdf-renderer#9`\n",
    )

    result = run_impl_review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        publish_plan_pull_request_url=None,
        publish_plan_pull_number=None,
        publish_result=type("PublishResultStub", (), {"status": "published", "target": "draft_pr", "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13", "pull_number": 13})(),
        reviewer=_stub_agent(_review_result(role="reviewer", status="approved", summary="Reviewer approves.")),
        architect=_stub_agent(_review_result(role="architect", status="approved", summary="Architect approves.")),
    )

    assert result.review_status == "approved"
    assert result.allows_downstream_automation is True
    assert result.pull_head_sha == "head-sha"
    assert comments == []


def test_run_impl_review_derives_live_pr_url_when_only_pull_number_is_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_approved_plan(tmp_path)
    comments: list[str] = []

    class StubWriter:
        def get_pull_request(self, owner: str, repo: str, pull_number: int):
            del owner, repo
            return {
                "number": pull_number,
                "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "head": {"sha": "head-sha"},
                "base": {"repo": {"name": "markdown-pdf-renderer", "owner": {"login": "cracklings3d"}}},
            }

        def create_issue_comment(self, reference, body):
            del reference
            comments.append(body)
            return "comment-url"

        def reopen_issue(self, reference):
            del reference

    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "- Run ID: `run-123`\n- Issue: `cracklings3d/markdown-pdf-renderer#9`\n",
    )

    result = run_impl_review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        publish_plan_pull_request_url=None,
        publish_plan_pull_number=13,
        publish_result=type(
            "PublishResultStub",
            (),
            {"status": "published", "target": "draft_pr", "url": None, "pull_number": 13},
        )(),
        reviewer=_stub_agent(_review_result(role="reviewer", status="approved", summary="Reviewer approves.")),
        architect=_stub_agent(_review_result(role="architect", status="approved", summary="Architect approves.")),
    )

    assert result.review_status == "approved"
    assert result.pull_request_url == "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13"
    assert result.pull_number == 13
    assert comments == []


@pytest.mark.parametrize("review_status", ["changes_requested", "blocked"])
def test_mirror_impl_review_to_post_publish_maps_stage_statuses(review_status: str) -> None:
    review = ImplReviewResult(
        review_status=cast(Literal["approved", "changes_requested", "blocked"], review_status),
        summary="summary",
        pull_request_url="https://example/pull/1",
        pull_number=1,
        pull_head_sha="sha",
    )

    mirrored = mirror_impl_review_to_post_publish(review)

    assert mirrored.status == ("rejected" if review_status == "changes_requested" else "failed_infra")


def test_run_impl_review_blocks_on_provenance_mismatch_and_posts_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_approved_plan(tmp_path)
    comments: list[str] = []

    class StubWriter:
        def get_pull_request(self, owner: str, repo: str, pull_number: int):
            del owner, repo
            return {
                "number": pull_number,
                "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "head": {"sha": "head-sha"},
                "base": {"repo": {"name": "markdown-pdf-renderer", "owner": {"login": "cracklings3d"}}},
            }

        def create_issue_comment(self, reference, body):
            del reference
            comments.append(body)
            return "comment-url"

        def reopen_issue(self, reference):
            del reference

    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "- Run ID: `run-other`\n- Issue: `cracklings3d/markdown-pdf-renderer#999`\n",
    )

    result = run_impl_review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        publish_plan_pull_request_url=None,
        publish_plan_pull_number=None,
        publish_result=type("PublishResultStub", (), {"status": "published", "target": "draft_pr", "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13", "pull_number": 13})(),
        reviewer=_stub_agent(_review_result(role="reviewer", status="approved", summary="Reviewer approves.")),
        architect=_stub_agent(_review_result(role="architect", status="approved", summary="Architect approves.")),
    )

    assert result.review_status == "blocked"
    assert result.issue_reopened is True
    assert result.issue_comment_url == "comment-url"
    assert any(item.code == "pr_body_run_id_mismatch" for item in result.feedback)
    assert comments and "Structured Feedback" in comments[0]


def test_run_impl_review_uses_canonical_validation_before_mapping_compatibility_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_approved_plan(tmp_path)

    class StubWriter:
        def get_pull_request(self, owner: str, repo: str, pull_number: int):
            del owner, repo
            return {
                "number": pull_number,
                "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "head": {"sha": "live-head-sha"},
                "base": {"repo": {"name": "markdown-pdf-renderer", "owner": {"login": "cracklings3d"}}},
            }

        def create_issue_comment(self, reference, body):
            del reference, body
            return "comment-url"

        def reopen_issue(self, reference):
            del reference

    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "- Run ID: `run-other`\n- Issue: `cracklings3d/markdown-pdf-renderer#9`\n",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review.run_post_publish_review",
        lambda **kwargs: pytest.fail("legacy review flow should not run when canonical provenance fails"),
    )

    result = run_impl_review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        publish_plan_pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
        publish_plan_pull_number=13,
        publish_result=type(
            "PublishResultStub",
            (),
            {
                "status": "published",
                "target": "draft_pr",
                "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "pull_number": 13,
            },
        )(),
        reviewer=_stub_agent(_review_result(role="reviewer", status="approved", summary="Reviewer approves.")),
        architect=_stub_agent(_review_result(role="architect", status="approved", summary="Architect approves.")),
    )

    assert result.review_status == "blocked"
    assert result.pull_head_sha == "live-head-sha"
    assert any(item.code == "pr_body_run_id_mismatch" for item in result.feedback)


def test_run_impl_review_posts_non_approved_side_effects_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_approved_plan(tmp_path)
    comments: list[str] = []
    reopen_calls = 0

    class StubWriter:
        def get_pull_request(self, owner: str, repo: str, pull_number: int):
            del owner, repo
            return {
                "number": pull_number,
                "html_url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "head": {"sha": "live-head-sha"},
                "base": {"repo": {"name": "markdown-pdf-renderer", "owner": {"login": "cracklings3d"}}},
            }

        def create_issue_comment(self, reference, body):
            del reference
            comments.append(body)
            return f"comment-url-{len(comments)}"

        def reopen_issue(self, reference):
            nonlocal reopen_calls
            del reference
            reopen_calls += 1

    monkeypatch.setattr(
        "precision_squad.post_publish_review.GitHubWriteClient.from_env",
        lambda token_env="GITHUB_TOKEN": StubWriter(),
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_body",
        lambda *args, **kwargs: "- Run ID: `run-123`\n- Issue: `cracklings3d/markdown-pdf-renderer#9`\n",
    )
    monkeypatch.setattr(
        "precision_squad.post_publish_review._fetch_pr_diff",
        lambda *args, **kwargs: "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
    )

    result = run_impl_review(
        intake=_intake(),
        run_record=_record(tmp_path),
        run_dir=tmp_path,
        publish_plan_pull_request_url="https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
        publish_plan_pull_number=13,
        publish_result=type(
            "PublishResultStub",
            (),
            {
                "status": "published",
                "target": "draft_pr",
                "url": "https://github.com/cracklings3d/markdown-pdf-renderer/pull/13",
                "pull_number": 13,
            },
        )(),
        reviewer=_stub_agent(
            _review_result(
                role="reviewer",
                status="rejected",
                summary="Reviewer requests changes.",
                feedback=("Fix the implementation review flow.",),
            )
        ),
        architect=_stub_agent(_review_result(role="architect", status="approved", summary="Architect approves.")),
    )

    assert result.review_status == "changes_requested"
    assert result.issue_comment_url == "comment-url-1"
    assert result.issue_reopened is True
    assert len(comments) == 1
    assert reopen_calls == 1
