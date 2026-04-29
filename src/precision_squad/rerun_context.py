"""Helpers for reusing previous rejected pull requests on reruns."""

from __future__ import annotations

import re
from dataclasses import dataclass

PR_URL_PATTERN = re.compile(
    r"^- PR: (?P<url>https://github\.com/[^/\s]+/[^/\s]+/pull/(?P<number>[0-9]+))\s*$",
    re.MULTILINE,
)
REJECTED_VERDICT_PATTERN = re.compile(
    r"^- (?:Reviewer|Architect) verdict: `rejected`$",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class RejectedPullRequestReference:
    url: str
    number: int


def latest_rejected_pull_request(
    comments: tuple[str, ...],
) -> RejectedPullRequestReference | None:
    for comment in reversed(comments):
        if "Precision Squad Review Feedback" not in comment:
            continue
        if REJECTED_VERDICT_PATTERN.search(comment) is None:
            continue
        match = PR_URL_PATTERN.search(comment)
        if match is None:
            continue
        return RejectedPullRequestReference(
            url=match.group("url"),
            number=int(match.group("number")),
        )
    return None
