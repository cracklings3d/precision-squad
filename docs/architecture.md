# Architecture

## Purpose

`precision-squad` is a docs-first workflow control system for issue repair.

The active design assumes that a repository should already explain how it is installed and how changes are verified. The system reads that documented contract, runs it locally, and makes its decisions visible through persisted artifacts, governance output, and GitHub publishing.

## Core Principle

Repository documentation is the execution contract.

That means:

- the repo should tell a newcomer how to set it up
- the repo should tell a newcomer what command proves a fix
- `precision-squad` should execute documented commands exactly instead of inventing replacements
- when the docs do not answer the obvious newcomer questions, the run should fail constructively and say what is missing

## System Boundary

`precision-squad` owns:

- GitHub issue intake
- local run creation and artifact persistence
- extraction of setup and QA commands from repo documentation
- repair-agent orchestration in an isolated worktree
- exact local QA execution in PowerShell
- governance decisions
- draft PR publishing, blocked issue comments, and follow-up repo issues
- post-publish reviewer and architect loops

`precision-squad` does not try to be:

- a generic multi-agent orchestration framework
- a deep repo inference engine
- a hidden substitute for missing setup or test docs
- a platform-normalization layer that rewrites one command into another and quietly trusts the result

## Execution Model

One `repair issue` run follows this flow:

1. Load and classify the GitHub issue.
2. Create a persisted run directory under `.precision-squad/runs/<run-id>/`.
3. Read the ordered documentation sources and extract a local execution contract.
4. Persist that contract under `execution-contract/`.
5. Clone the target repo into `repair-workspace/repo`.
6. Ask the repair agent to modify the isolated workspace using the documented contract as source of truth.
7. Run the documented setup commands and documented QA command in PowerShell.
8. Apply governance.
9. Prepare a draft PR, blocked issue comment, or follow-up repo issue.
10. Optionally publish and run post-publish review.

## Execution Contract

The executor writes a machine-readable contract artifact directory:

- `execution-contract/contract.json`
- `execution-contract/README.snapshot.md`
- `executor.stdout.log`
- `executor.stderr.log`

The contract contains:

- the source documentation path
- extracted setup commands
- the extracted QA command
- notes about what was found
- questions about what is still unclear

This is intentionally small and inspectable.

## Contract Extraction Rules

The current executor is `DocsFirstExecutor`.

It:

- looks for an ordered set of doc sources, currently including:
  - `README.md`, `readme.md`, `README.rst`, `README.txt`
  - `CONTRIBUTING.md`, `contributing.md`
  - selected top-level docs pages such as `docs/README.md`, `docs/getting-started.md`, `docs/setup.md`, and `docs/testing.md`
- searches for setup-oriented headings such as `Installation`, `Setup`, `Development`, and `Getting Started`
- searches for test-oriented headings such as `Tests`, `Testing`, `Quality`, and `Verification`
- extracts inline or line-oriented commands that look like:
  - `python ...`
  - `python -m ...`
  - `py ...`
  - `pip ...`
  - `uv ...`
  - `poetry ...`
  - `pytest ...`

The extractor is backed by an explicit documentation policy layer.

That policy is now sourced from a packaged JSON checklist rather than only hardcoded Python constants.

The checklist is intended to act like a flight checklist for documentation quality:

- the executor uses it to detect blocking documentation defects
- docs-fix prompts are generated from it
- future doc-authoring or doc-checking agent skills can reuse the same checklist with minimal context

That policy currently asks whether the docs provide:

- a canonical project-facing entrypoint
- a canonical setup command
- a canonical QA command
- an unambiguous setup path
- an unambiguous QA path
- a brief explanation of what the documented commands are for

If the docs are incomplete, the executor fails with a constructive summary written from a newcomer point of view.

Examples of failure themes:

- there are no project-facing docs at all
- there is no documented install command
- there is no documented QA command
- a section exists, but it still does not tell a new contributor what exact command to run
- two doc sources describe competing setup or QA paths

The executor uses explicit docs-specific outcomes:

- `missing_docs`: the repository does not document a usable local contract
- `ambiguous_docs`: the repository documents multiple competing contracts and the workflow cannot safely choose one

The same policy rules are used for two purposes:

- identify holes in existing documentation
- generate the `docs-fix-prompt.txt` artifact that tells an agent or user what documentation must be added or clarified

The policy now distinguishes between:

- exact executable setup steps
- human-readable manual prerequisite guidance
- hidden environment assumptions
- verification gaps that leave setup uncertain for automation

Examples of newly blocking documentation defects:

- docs say to download a prerequisite from a URL but do not specify the exact version or release to use
- docs say to run an installer but do not provide an exact verification command afterward
- docs assume a terminal restart, PATH change, DLL discovery, or other environment mutation without making that assumption explicit and verifiable
- docs mention an external prerequisite but do not say whether the canonical path is a package-manager install, release artifact, or source build

These conditions are intentionally blocking even when a human could plausibly infer the next step, because the active design treats avoidable uncertainty as a documentation defect that should be fixed quickly and explicitly.

## Repair Stage

The repair runtime is currently `OpenCodeRepairAdapter`.

It:

- prepares an isolated clone in `repair-workspace/repo`
- passes the issue statement, execution contract, documentation snapshot, and prior QA feedback to `opencode`
- captures:
  - `repair.stdout.log`
  - `repair.stderr.log`
  - `repair-transcript.json`
  - `repair.patch`

The repair agent is expected to make focused code changes without committing.

## QA Model

The QA verifier is intentionally stricter than the old architecture.

It:

- loads `contract.json`
- executes each documented setup command exactly in PowerShell
- executes the documented QA command exactly in PowerShell
- does not rewrite `uv run pytest ...` into `python -m pytest ...`
- does not parse shell scripts and guess what the real command was

The only tool bootstrapping currently allowed is a whitelist-driven install attempt for:

- `uv`
- `poetry`

If a documented QA command requires one of those tools and it is missing locally, the verifier may try:

- `python -m pip install uv`
- `python -m pip install poetry`

If that fails, the run fails constructively.

The verifier distinguishes several outcomes:

- `passed`: the documented verifier ran and passed
- `failed`: the documented verifier ran and reported real failing checks
- `unrunnable`: the QA command was extracted, but it did not produce a trustworthy verification signal
- `failed_infra`: setup or tooling failed before the documented contract could be exercised reliably

Examples of `unrunnable` outcomes:

- command not found
- invalid test target path
- pytest usage/config/collection errors
- no tests ran when a real verifier was expected

## Baseline Handling

The system still preserves baseline-aware QA semantics.

It runs:

- baseline QA against a clean clone of the original repo
- final QA against the repaired workspace

If the final state is strictly better than a broken baseline without introducing new failures, governance may classify the run as `provisional` instead of `approved`.

This is a pragmatic escape hatch for broken repos, not a substitute for green QA.

## Governance

Governance has three outcomes:

- `approved`
- `provisional`
- `blocked`

Current intent:

- `approved`: documented setup and QA evidence is present and passes
- `provisional`: the run improved a broken baseline but is not fully green
- `blocked`: intake, documentation, execution, or QA evidence is missing, ambiguous, unrunnable, or failed

Publish behavior:

- `approved` and `provisional` runs can produce draft PRs
- `blocked` docs-policy runs from otherwise runnable issues can produce follow-up repo issues instead
- other `blocked` runs produce issue comments instead

The follow-up-issue path exists for cases where the newly discovered blocker is real but unrelated to the source issue's requested code change. In those cases, publishing back under the source issue would misfile the problem.

When a follow-up docs-remediation issue is itself repaired, the system does not trust the repair prompt alone. It reruns the same docs extractor and JSON-checklist gate against the repaired workspace and only approves the run if the repaired docs clear that same gate.

Follow-up docs issues are also deduplicated by blocker fingerprint. If two separate source issues surface the same remaining docs blocker shape, publish will reuse the existing open docs-remediation issue instead of creating a duplicate issue for the same unresolved blocker.

The active fingerprint is no longer based only on a human-facing summary. It is derived from structured findings emitted by the docs extractor, using stable fields such as rule ID, normalized source path, normalized section key, and a rule-specific normalized subject key.

## Publishing And Review

Publishing uses the stored repair workspace rather than rerunning repair.

The publish executor:

- copies `repair-workspace/repo` into `publish-workspace`
- strips transient artifacts such as cache directories and `.pyc` files
- commits the repaired state on a generated branch
- creates a draft PR

After publish, local review agents can inspect the PR as:

- `reviewer`
- `architect`

If either rejects the PR, `precision-squad`:

- posts structured feedback back to the GitHub issue
- reopens the issue
- persists a `post-publish-review-result.json`

## Persistence Model

Run state is filesystem-backed and transparent.

Important persisted artifacts include:

- `run-request.json`
- `issue-intake.json`
- `run-record.json`
- `execution-result.json`
- `evaluation-result.json`
- `governance-verdict.json`
- `publish-plan.json`
- `publish-result.json`
- `repair-result.json`
- `qa-baseline-result.json`
- `qa-result.json`
- `post-publish-review-result.json`

This is deliberate. The system prefers inspectability and replayability over hidden state.

## Design Choices

### Why Docs-First

The current design assumes that well-maintained repos should already answer:

- how do I install this?
- how do I run tests?
- what exact command proves the fix?

When those answers are missing, the system should make the missing documentation visible instead of inventing hidden repo-specific inference.

### Why Exact Execution

The system no longer tries to normalize commands into a supposedly equivalent form.

Reason:

- exact execution is trustworthy
- rewritten commands are weaker evidence
- silent command translation can approve the wrong thing without noticing

### Why Constructive Failure

A plain "file missing" or "command not found" error is not enough.

The failure should explain the perspective of a newcomer trying to use the repo for the first time. That often exposes the real documentation gap more clearly than a raw mechanical error.

## Current Non-Goals

The active architecture does not try to provide:

- hidden recovery for poorly documented repos
- shell command equivalence reasoning
- automatic derivation of the right test command when the docs do not say it
- a database-backed execution service
- remote runner orchestration

## Archived Designs

Older planning documents are retained under `docs/archive/` for historical reference only. They are not the active architecture.
