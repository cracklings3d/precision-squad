"""Templates for bootstrap managed files."""

from __future__ import annotations

DEFAULT_CONFIG_TEMPLATE = """# precision-squad managed config
# This file is managed by precision-squad bootstrap.
# Manual edits to this file may be overwritten by bootstrap.
# To remove bootstrap state, delete this directory and root SKILL.md.

[repair.issue]
# Default repair agent for this project
repair_agent = "opencode"

# Runs directory for this project
runs_dir = ".precision-squad/runs"

[create.issue]
runs_dir = ".precision-squad/runs"

[review.issue]
runs_dir = ".precision-squad/runs"

[plan]
runs_dir = ".precision-squad/runs"

[implement]
repo_path = "."
runs_dir = ".precision-squad/runs"
repair_agent = "opencode"

[publish.run]
runs_dir = ".precision-squad/runs"

[install-skill]
project_root = "."
"""

SKILL_TEMPLATE = """# Precision Squad

Use `precision-squad` as the control plane for issue-driven work in this repository.

## Primary Commands

Repair a GitHub issue from the local checkout:

```bash
python -m precision_squad.cli repair issue owner/repo#number --repo-path . --publish
```

Publish a stored run without rerunning repair:

```bash
python -m precision_squad.cli publish run <run-id>
```

## Workflow Rules

- Start from an existing GitHub issue.
- Use `repair issue` first.
- If the result is `draft_pr`, continue with PR review.
- If the result is `follow_up_issue`, switch to that docs-remediation issue.
- If the result is `issue_comment`, read the blocked feedback on the issue.

## Docs-Remediation Issues

Treat an issue as a docs-remediation issue if the body contains markers like:

- `<!-- precision-squad:docs-remediation -->`
- `<!-- precision-squad:target-findings:... -->`
- `<!-- precision-squad:baseline-findings:... -->`

When that happens:

- rerun the same issue instead of creating a new one
- use the target findings as the scope of the work
- baseline findings may remain if target findings are cleared
- if target findings remain, the issue should stay blocked and receive feedback

## Operator Guidance

- Prefer the local checkout as `--repo-path .` when you are already in the project root.
- Publish outcomes so later reruns inherit GitHub feedback.
- Trust structured target findings more than high-level prose summaries.
- If multiple reruns keep failing on the same target findings, stop blindly
  retrying and reassess the prompt, policy, or underlying dependency.
"""
