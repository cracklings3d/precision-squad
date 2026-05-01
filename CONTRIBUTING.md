# Contributing to precision-squad

`precision-squad` is a docs-first workflow control system. Contributing means working within the issue-first process described below, respecting the governance model, and maintaining the project's standards for code, tests, and documentation.

---

## Repository

https://github.com/cracklings3d/precision-squad.git

---

## Development Setup

```bash
# Clone the repository
git clone https://github.com/cracklings3d/precision-squad.git
cd precision-squad

# Install in dev mode (includes linting, type-checking, and test tooling)
python -m pip install -e ".[dev]"
```

---

## Running Local Checks

Before opening a pull request, run all three check targets:

```bash
ruff check .       # Linting (E, F, I rules)
pyright            # Static type analysis
pytest             # Unit and integration tests
```

### Integration Tests

Some tests are marked `integration` and require a `GITHUB_TOKEN` environment variable with a GitHub personal access token, plus network access to the GitHub API. These are skipped automatically when the token is absent.

```bash
GITHUB_TOKEN=ghp_... pytest -m integration
```

### Python Version

The project requires **Python 3.14 or later**. If you are using an older version, the CI will fail.

---

## Issue-First Workflow

This repository follows a strict **issue-first GitHub workflow**:

1. **Open an issue** describing the problem or change before writing any code.
2. **Link a PR** to that issue. PRs without a corresponding issue will be closed.
3. **Scope the PR to the issue.** Avoid scope creep; one PR per issue.
4. **Include a closing reference** in the PR description, e.g. `Closes #8`.

### Issue Labels

- `phase-X` — implementation phases tracked across the roadmap
- `documentation` — docs-only work
- `tests` — test additions or updates
- `bug`, `enhancement`, `refactor` — standard categories

---

## Governance Model

Every repair run produces a **governance verdict** that determines what happens next.

### Verdict: Approved

The run passed governance. A draft PR is created automatically. No further human action is required before the PR is reviewed.

### Verdict: Blocked

The run did not pass governance. A `requires_review` or `follow_up_issue` action is created. Human action is required before publishing.

### Quality Tag

Every `ExecutionResult` carries a **quality tag** that describes the relationship between the baseline and final QA outcomes:

| Tag | Meaning |
|---|---|
| `green` | Baseline passed, or final matches baseline (no new failures) |
| `improved` | Baseline failed; final has fewer failures |
| `degraded` | New failures were introduced by the repair |

Quality tags are informational. The **verdict (approved/blocked) is what gates publishing**.

---

## Side Issues

During a repair, the agent may discover problems that are unrelated to the primary issue being worked. These are called **side issues**.

Side issues are surfaced via a `side_issues` field on `RepairResult`. When a run is blocked, each side issue becomes a `follow_up_issue` action in the publish plan — a separate issue is opened on your behalf with the relevant details.

This means: even a blocked run can leave you with clean, actionable follow-up work rather than one large ambiguous comment.

---

## Retry Policy

If a repair does not produce an approved verdict, you can retry manually:

```bash
python -m precision_squad.cli repair issue owner/repo#number --retry-from <run-id>
```

- Up to **3 retry attempts** are allowed before the run is marked `escalated`.
- Retries are always manual — there is no automatic retry loop.

---

## Docs-First Principle

`precision-squad` treats repository documentation as the execution contract. This project practices what it preaches:

- **Setup and QA commands** are extracted from the repository's own docs.
- A `docs-fix-prompt.txt` file is generated when documentation quality issues are detected.
- For **docs-remediation issues**, the `docs-fix-prompt.txt` content **is the fix specification itself**.
- For **non-docs-remediation issues**, the presence of `docs-fix-prompt.txt` signals that side issues exist and should be surfaced as separate issues.

---

## What to Contribute

### High-Value Contributions

- **Phase issues** (issues labeled `phase-X`) represent the planned implementation roadmap.
- **ADR documents** (`docs/adr/`) capture irreversible architectural decisions.
- **Tests** for uncovered modules, especially edge cases in `executor.py`, `coordinator.py`, and `github_client.py`.
- **Documentation improvements** that clarify the docs-first contract or operator workflow.

### Not in Scope for V1

Please do not open PRs for the following unless discussed in an issue first:

- GitHub App authentication
- MCP or remote runner support
- Database-backed persistence
- Multi-tenant or broad parallel execution
- Deep repo-specific inference machinery

These are listed as non-goals in the project scope and will be closed.

---

## PR Checklist

Before requesting review:

- [ ] `ruff check .` passes with no new violations
- [ ] `pyright` reports 0 errors
- [ ] `pytest` passes (integration tests skipped if no `GITHUB_TOKEN`)
- [ ] New code has corresponding tests
- [ ] PR description links to the issue it resolves and includes a closing reference
- [ ] If changing behavior that affects the governance or publishing flow, the corresponding ADR (in `docs/adr/`) is updated or created

---

## Getting Help

If you are unsure whether a contribution is in scope, open a discussion issue first. For questions about the repair workflow, governance model, or the docs-first principle, the `docs/operator-skill.md` provides a practical walkthrough.
