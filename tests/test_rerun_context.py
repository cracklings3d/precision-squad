"""Tests for rejected PR rerun context resolution."""

from __future__ import annotations

from precision_squad.rerun_context import latest_rejected_pull_request


def test_latest_rejected_pull_request_returns_latest_rejected_feedback() -> None:
    comments = (
        """## Precision Squad Review Feedback
- Run ID: `run-1`
- PR: https://github.com/foo/bar/pull/13
- Reviewer verdict: `rejected`
""",
        """## Precision Squad Review Feedback
- Run ID: `run-2`
- PR: https://github.com/foo/bar/pull/15
- Reviewer verdict: `approved`
- Architect verdict: `approved`
""",
        """## Precision Squad Review Feedback
- Run ID: `run-3`
- PR: https://github.com/foo/bar/pull/18
- Reviewer verdict: `rejected`
- Architect verdict: `approved`
""",
    )

    result = latest_rejected_pull_request(comments)

    assert result is not None
    assert result.number == 18
    assert result.url == "https://github.com/foo/bar/pull/18"


def test_latest_rejected_pull_request_returns_none_without_rejection() -> None:
    result = latest_rejected_pull_request(
        (
            """## Precision Squad Review Feedback
- PR: https://github.com/foo/bar/pull/15
- Reviewer verdict: `approved`
""",
        )
    )

    assert result is None
