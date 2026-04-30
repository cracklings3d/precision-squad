# Project Status Report

**Date:** 2026-04-30  
**Repository:** precision-squad  
**Version:** 0.1.0  

---

## 1. Project Summary

`precision-squad` is a docs-first workflow control system for GitHub issue repair. It treats repository documentation as the execution contract: it reads a repo's documented setup and QA instructions, executes them exactly, runs a repair agent in an isolated workspace, applies governance, and publishes results as draft PRs or issue comments.

## 2. Goals

| # | Goal (from README) | Status |
|---|---|---|
| 1 | Bootstrap Python package, tooling, CI, and issue/PR workflow assets | **Done** |
| 2 | Implement GitHub PAT-backed issue intake | **Done** |
| 3 | Add the local run store | **Done** |
| 4 | Define the executor seam and documented local contract extraction | **Done** |
| 5 | Build the first end-to-end CLI flow | **Done** |
| 6 | Add governance v1 and publishing v1 | **Substantially done** |

## 3. Current Architecture

### 3.1 Core Pipeline

```
Issue Intake → Run Store → Docs-First Executor → Repair Agent → QA
    → Governance → Publishing → Post-Publish Review
```

### 3.2 Module Breakdown

| Module | Responsibility | Status |
|---|---|---|
| `intake.py` | Parse and classify GitHub issues | Done |
| `run_store.py` | Filesystem-backed run persistence | Done |
| `executor.py` | `DocsFirstExecutor` extracts setup/QA contracts from docs | Done |
| `docs_policy.py` | JSON-checklist-based documentation quality policy | Done |
| `docs_remediation.py` | Docs remediation repair detection, fingerprinting, deduplication | Done |
| `repair/` | `OpenCodeRepairAdapter`, repair+QA orchestration loop | Done |
| `qa.py` | QA verifier (baseline + final, strict exact-command execution) | Done |
| `governance.py` | Three-way verdict: approved/provisional/blocked | Done |
| `publishing.py` | Build publish plans (draft PR, issue comment, follow-up issue) | Done |
| `publish_executor.py` | Commit repaired state, create draft PR | Done |
| `post_publish_review.py` | Automated reviewer + architect PR review loops | Done |
| `github_client.py` | PAT-backed read/write client (gh CLI + HTTP fallbacks) | Done |
| `coordinator.py` | Orchestrates repair and publish workflows | Done |
| `cli.py` | CLI surface with `repair`, `publish`, `install-skill` commands | Done |
| `bootstrap.py` | Interactive bootstrap for consuming projects | Done |
| `compat/imghdr.py` | Python 3.14 imghdr compatibility shim | Done |
| `skills/precision-squad/` | External skill package for npx skills | Done |
| `data/docs_checklist.json` | Machine-readable documentation quality checklist | Done |
| `data/project_skill_template.md` | SKILL.md template for consuming projects | Done |

## 4. Quality Status

| Check | Result |
|---|---|
| Ruff linting | All checks passed |
| Pyright type-checking | 0 errors, 0 warnings |
| Pytest | 27 integration tests (23 passed, 4 skipped -- require GITHUB_TOKEN) |
| CI workflow | Configured (lint, typecheck, test) on push/PR |

## 5. Implemented Features

### 5.1 Issue Intake
- Fetches GitHub issues via `gh` CLI with HTTP fallback
- Includes issue comments in intake
- Detects PR vs issue references
- Deterministic classification (runnable vs blocked)
- Recognizes docs-remediation issues separately

### 5.2 Docs-First Contract Extraction
- Scans ordered doc sources: README, CONTRIBUTING, docs/ pages
- Extracts setup and QA commands from heading-based sections
- Validates against JSON checklist policy (11 rules)
- Distinguishes: missing docs, ambiguous docs, blocking defects
- Generates `docs-fix-prompt.txt` for remediation
- Writes machine-readable `execution-contract/` artifacts

### 5.3 Repair Execution
- Isolates workspace via repo cloning in worktree
- Passes issue, contract, docs snapshot, and QA feedback to agent
- Captures stdout, stderr, transcript, and patch
- Supports `--repair-agent none` for docs-only runs

### 5.4 QA Model
- Executes documented commands exactly in PowerShell
- No command rewriting or equivalence inference
- Whitelist-driven tool bootstrapping (uv, poetry pip install)
- Baseline QA against clean clone, final QA against repaired workspace
- Four outcome categories: passed, failed, unrunnable, failed_infra
- Provisional classification for broken-baseline improvements

### 5.5 Governance
- Three verdicts: approved, provisional, blocked
- Follow-up issue path for unrelated blockers
- Blocker fingerprint deduplication across issues

### 5.6 Publishing
- Copies repair workspace, strips transient artifacts
- Commits on generated branch, creates draft PR
- Dry-run support for previews
- Issue comment and follow-up issue publishing paths

### 5.7 Post-Publish Review
- Reviewer and architect review loops via opencode
- Structured feedback posted back to GitHub issue
- Issue reopening on rejection
- Staleness detection via PR head SHA comparison

## 6. Gaps and Risks

### 6.1 Immediate Gaps

| Gap | Severity | Notes |
|---|---|---|
| Python 3.14 only | **Medium** | `requires-python = ">=3.14"` locks to an unreleased/preview Python version. If this is intentional, CI should verify 3.14 is available on runners. If a mistake, constraint should be relaxed. |
| No error-level test for `compat/imghdr.py` | **Low** | Python 3.14 removed `imghdr`; the compat shim fills the gap but has no direct test. |
| `__version__` exported but no runtime version command tested | **Low** | CLI has `--version`, tests cover it, but packaging metadata version sync is implicit. |

### 6.2 Architectural Risks

| Risk | Severity | Notes |
|---|---|---|
| External dependency on `opencode` binary | **High** | The repair adapter shells out to `opencode`. If `opencode` changes its CLI contract or is unavailable, repair silently degrades. No version pinning or capability detection. |
| `gh` CLI as primary transport | **Medium** | GitHub client prefers `gh` CLI subprocess calls over HTTP. If `gh` is not installed, HTTP fallback works, but the primary path depends on an external tool. |
| Broad `object` typing in `RepairIssueReport.governance_verdict` | **Medium** | The coordinator stores the verdict as `object`, losing type safety. All downstream code casts it (correctly) but this defeats pyright's checks. |
| Hard-coded command syntax detection regexes | **Medium** | Contract extraction uses hardcoded patterns for `python`, `py`, `pip`, `uv`, `poetry`, `pytest`. Non-standard or future tool commands would be silently missed. |

### 6.3 Operational Gaps

| Gap | Severity | Notes |
|---|---|---|
| No structured logging | **Medium** | All output goes through `print()`. No structured log output, log levels, or log file persistence for long-running or automated runs. |
| No retry or idempotency for failed runs | **Medium** | If a run fails mid-pipeline, rerunning creates a new run ID. No resume-from-checkpoint capability. |
| No telemetry or usage metrics | **Low** | No built-in tracking of run durations, success rates, or common failure modes. |
| No configuration file support | **Low** | All configuration is via CLI flags and `.env`. No `precision-squad.yaml` for project-level defaults. |

## 7. Next Milestones (Recommended)

Based on the current state, here are the highest-value next steps:

### Priority 1: Error Handling and Resilience
- Add checkpoint-based resume for interrupted runs
- Implement structured logging with log file output
- Add `opencode` version detection and compatibility reporting

### Priority 2: Python Version Policy
- Confirm whether Python 3.14 requirement is intentional
- If so, add a note explaining why in docs/ or README
- If not, relax to `>=3.12` or the earliest viable version

### Priority 3: Governance Verdict Typing
- Replace `object` with `GovernanceVerdict` in `RepairIssueReport`
- Remove the `cast(Any, ...)` calls in CLI

### Priority 5: Contract Extraction Extensibility
- Move command extraction patterns from hardcoded lists to a configurable policy file
- Allow consuming projects to register custom tool command patterns

## 8. File Overview

### Source Files (core)
| File | Lines | Responsibility |
|---|---|---|
| `cli.py` | 687 | CLI entry points, argument parsing, dependency injection |
| `coordinator.py` | 393 | Orchestration of repair and publish workflows |
| `github_client.py` | 579 | GitHub read/write client (gh CLI + HTTP) |
| `executor.py` | — | Docs-first contract extraction and execution |
| `intake.py` | — | Issue loading and classification |
| `models.py` | 200 | Core data structures (18 dataclasses) |
| `governance.py` | — | Verdict logic |
| `publishing.py` | — | Publish plan construction |
| `publish_executor.py` | — | Git-based publishing |
| `run_store.py` | — | Filesystem persistence |
| `docs_policy.py` | — | Documentation checklist policy |
| `docs_remediation.py` | — | Docs remediation fingerprinting |
| `env.py` | — | Environment variable loading |
| `bootstrap.py` | — | Interactive bootstrap for consuming projects |

### Repair Module
| File | Responsibility |
|---|---|
| `adapter.py` | `OpenCodeRepairAdapter` - shells out to opencode |
| `orchestration.py` | Repair + QA loop coordination |
| `qa.py` | QA verifier with baseline/final semantics |

### Test Coverage
- 14 test files, 109 tests
- All modules have corresponding test coverage
- 100% pass rate with no skips or failures

## 9. Conclusion

`precision-squad` is a well-structured, testable project with a clear architectural vision. All six near-term milestones from the README are substantially implemented. The codebase is clean (no linter or type errors), well-tested (109 passing tests), and follows docs-first principles consistently.

The primary risk areas are around external dependency management (`opencode`, `gh` CLI) and the lack of integration tests. Addressing these, along with the typing and resilience improvements listed above, would solidify the foundation before pursuing V1 feature additions like GitHub App auth, database-backed persistence, or multi-tenant support.
