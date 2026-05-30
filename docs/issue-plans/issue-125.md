---
issue: github.com/cracklings3d/precision-squad#125
title: "[Task]: Add one-command Windows + opencode deploy/bootstrap with self-contained boundary"
status: approved
plan_status: approved
review_status: approved
source: issue
owner: cracklings3d
created_at: 2026-05-30
updated_at: 2026-05-30
approved_by: "canonical-issue-resolver stage-D review"
approved_at: 2026-05-29T17:30:00Z
review_artifact: 'C:\Users\The_u\.opencode\projects\github-com-cracklings3d-precision-squad\runs\canonical-issue-resolver-parallel\cirp-20260529T173000-template-recovery\reviews\issue-125\loop-1-stage-D.json'
related_branch: issue/125
related_pr: null
replaces: null
supersedes: null
change_scope:
  files:
    - README.md
    - docs/operator-skill.md
    - docs/staged-command-surface.md
    - pyproject.toml
    - src/precision_squad/bootstrap.py
    - src/precision_squad/cli.py
    - src/precision_squad/config.py
    - src/precision_squad/data/project_skill_template.md
    - tests/test_cli.py
    - tests/test_config.py
  directories:
    - src/precision_squad/deploy/
    - src/precision_squad/data/deploy/
  modules:
    - precision_squad.bootstrap
    - precision_squad.cli
    - precision_squad.config
    - precision_squad.deploy
  artifacts:
    - SKILL.md
    - .precision-squad/precision-squad.toml
    - .precision-squad/bootstrap/**
---

# Summary

Issue #125 should establish one canonical Windows PowerShell bootstrap command for the supported `opencode` path and retire the current fragmented setup story. The governing direction is to keep `precision-squad-bootstrap-skill --project-root .` as the sole documented operator-facing entrypoint, expand it from a SKILL-only helper into full repo bootstrap, and keep the generated repo-local surface bounded to root `SKILL.md` plus a dedicated `.precision-squad/` boundary that is easy to inspect and remove later.

# Problem

The current bootstrap surface is incomplete and split across multiple partial paths. `src/precision_squad/bootstrap.py` only installs `SKILL.md`, `src/precision_squad/cli.py` exposes `install-skill` but no full deploy/bootstrap flow, and the README currently recommends a command that does not leave a consuming repo fully ready for normal `precision-squad` use. Without one canonical path, operators can end up with overlapping or partial setup states.

# Acceptance Criteria

- One canonical operator-facing deploy/bootstrap command exists for Windows PowerShell.
- Scope remains explicitly limited to Windows + `opencode`.
- Running the command in a consuming repo performs the supported bootstrap flow:
  - validates or confirms the `precision-squad` CLI entrypoint the repo will use
  - writes project-local `SKILL.md`
  - writes the project-local config defaults required for the supported `opencode` path
  - validates required prerequisites and fails with actionable remediation when they are missing
- The deployed surface is self-contained, bounded, and easy to remove later.
- Deploy/bootstrap implementation code and assets live in a dedicated subdirectory instead of being scattered.
- Integration with the existing CLI stays minimal and explicit.
- Reruns are safe and report what was reused, updated, created, or already satisfied.
- On success, the consuming repo is ready for the normal documented `precision-squad` workflow without further `precision-squad`-specific setup.
- README and operator documentation show the exact one-command flow.
- Tests cover happy path, rerun/idempotency, existing `SKILL.md` / config handling, prerequisite failures, and removal expectations.
- Tests explicitly cover the current root-config precedence case: if `./.precision-squad.toml` already exists, bootstrap stops with actionable remediation before writing managed config, including when that root file is exactly equivalent to the desired nested config.

# In Scope

- Expand the current `precision-squad-bootstrap-skill` entrypoint from a SKILL-only installer into the canonical Windows + `opencode` bootstrap flow.
- Add a dedicated deploy/bootstrap package under `src/precision_squad/deploy/` and keep `src/precision_squad/bootstrap.py` as a thin operator-facing wrapper.
- Keep repo-local generated state bounded to root `SKILL.md` plus `.precision-squad/` managed content, with `.precision-squad/precision-squad.toml` as the canonical config location so bootstrap state stays inside the removable boundary.
- Validate Windows-only execution and the prerequisites the supported path actually depends on before writing files.
- Make rerun behavior explicitly idempotent and visible.
- Update README and operator docs so they describe the same canonical bootstrap path and the post-bootstrap workflow.
- Add or update focused tests for the bootstrap surface and config behavior only in `tests/test_cli.py` and `tests/test_config.py`.

# Out Of Scope

- Linux or macOS bootstrap support.
- Repair-agent support other than `opencode`.
- Refactoring unrelated staged workflow commands or changing the seven-stage issue-processing chain.
- Creating a second long-term bootstrap path alongside the canonical command.
- Solving the broader docs/skill gap tracked by issue #121 beyond the docs changes needed to document the canonical deploy/bootstrap path.

# Constraints

- The canonical operator command for this issue is `precision-squad-bootstrap-skill --project-root .`; `install-skill` remains a lower-level helper and must not remain an equally documented bootstrap alternative.
- Generated repo-local state outside the codebase should stay limited to root `SKILL.md` plus `.precision-squad/` content; no other precision-squad-specific bootstrap sprawl should be introduced.
- Config defaults must use the existing command-shaped config schema rather than inventing a second config format.
- Existing user-managed `SKILL.md` or config files must not be silently overwritten; conflict handling must be explicit.
- Because current config discovery prefers `./.precision-squad.toml` over `./.precision-squad/precision-squad.toml`, bootstrap must treat any existing root `./.precision-squad.toml` as a blocking conflict rather than silently reusing or migrating it in this issue, even when that root file is exactly equivalent to the desired nested managed config.
- The prerequisite contract for bootstrap is: validate Windows execution, validate that `--project-root` resolves to an accessible target for managed writes, validate the usable `precision-squad` CLI entrypoint for subsequent workflow commands, validate `opencode` availability, and reuse the current repair-entry GitHub credential prerequisite rules verbatim rather than inventing a bootstrap-specific token policy.
- `change_scope` is authoritative for allowed implementation and validation surface; bootstrap/config test coverage for this issue must stay within `tests/test_cli.py` and `tests/test_config.py`, and no new bootstrap-specific test module is in scope.
- Removal expectations must be clear from the bounded generated surface itself; this issue does not need to grow into a broad cleanup/refactor of unrelated repo files.

# Proposed Approach

1. Create a dedicated deploy/bootstrap implementation package under `src/precision_squad/deploy/` with explicit responsibilities for prerequisite validation, desired-file rendering, idempotent comparison/writes, and operator-facing result reporting. Keep `src/precision_squad/bootstrap.py` as the thin entrypoint that parses arguments and delegates into this package.
2. Treat `precision-squad-bootstrap-skill --project-root .` as the only canonical bootstrap command and update its flow so it validates the supported environment before writing anything: Windows-only execution, an accessible target project root, the usable `precision-squad` CLI entrypoint for subsequent workflow commands, `opencode` availability, and the same GitHub credential prerequisite rules already enforced by the current repair entrypoint.
3. Write only the minimal managed repo-local assets required for the supported path, and only when no root `./.precision-squad.toml` is present:
   - root `SKILL.md`
   - `.precision-squad/precision-squad.toml` with only the command-shaped defaults needed for repo-root `precision-squad` use on the `opencode` path
   - deploy-owned metadata inside `.precision-squad/bootstrap/` to support rerun reporting and make the managed boundary/removal expectations explicit
4. Make reruns deterministic by comparing current versus desired managed content and reporting per-item outcomes such as created, updated, reused, or already satisfied. If a conflicting `SKILL.md` or config file exists and is not deploy-managed, stop with actionable remediation instead of clobbering it. Under the current discovery precedence, any existing root `./.precision-squad.toml` is a blocking conflict even when its contents are exactly equivalent to the desired nested managed config, because the root file would still shadow the managed boundary.
5. Keep CLI integration explicit and small: do not refactor unrelated stage commands; only touch shared CLI/config seams that are necessary to validate the installed entrypoint, preserve command-shaped config rules, or keep `install-skill` clearly documented as a narrow helper rather than the canonical bootstrap path.
6. Update `README.md`, `docs/operator-skill.md`, and `docs/staged-command-surface.md` so they all point to the same one-command bootstrap flow, make the Windows + `opencode` limitation explicit, and document the bounded removal expectations.
7. Keep the validation surface aligned with `change_scope`: add the needed bootstrap/config cases in `tests/test_cli.py` and `tests/test_config.py` rather than authorizing a separate bootstrap-specific test module.

# Impacted Areas

- `src/precision_squad/bootstrap.py`
- `src/precision_squad/deploy/` (new dedicated implementation package)
- `src/precision_squad/data/deploy/` (new deploy/bootstrap templates or static assets)
- `src/precision_squad/config.py`
- `src/precision_squad/cli.py` (only if needed for explicit helper integration or help-text demotion of non-canonical paths)
- `src/precision_squad/data/project_skill_template.md`
- `README.md`
- `docs/operator-skill.md`
- `docs/staged-command-surface.md`
- `tests/test_cli.py`
- `tests/test_config.py`
- no additional bootstrap-specific test module; bootstrap/config coverage remains in `tests/test_cli.py` and `tests/test_config.py`

# Validation Plan

- Verify the canonical bootstrap command succeeds on the supported Windows path and leaves the target repo with the managed bootstrap surface expected by the plan.
- Verify rerunning the command is idempotent and reports whether managed files were created, updated, reused, or already satisfied.
- Verify existing `SKILL.md` and existing config scenarios are handled explicitly: identical managed content is reused, while conflicting unmanaged content produces actionable remediation.
- Verify an existing root `./.precision-squad.toml` causes bootstrap to stop before writing files, including when that root file is exactly equivalent to the desired nested config, because current discovery precedence would otherwise shadow the managed config boundary.
- Verify prerequisite failures produce targeted messages for the supported path instead of partial writes: unsupported non-Windows execution, inaccessible target project root, unusable `precision-squad` CLI entrypoint, missing `opencode`, and the same missing-GitHub-credential cases already enforced by the current repair entrypoint.
- Verify README/operator docs show the exact same canonical one-command flow and do not continue recommending a second competing bootstrap path.
- Verify removal expectations are testable from the bounded generated surface: the managed `.precision-squad/` boundary plus generated root `SKILL.md` are sufficient to describe what later cleanup would remove.

# Risks

- Expanding the existing bootstrap script without clearly demoting `install-skill` could leave two competing bootstrap stories; mitigate by making the canonical command explicit in code and docs.
- Writing config or `SKILL.md` too aggressively could overwrite user-managed content; mitigate with managed-surface detection and explicit conflict reporting.
- Allowing generated assets to spread outside the declared boundary would weaken removability; mitigate by keeping managed outputs centered on `.precision-squad/` plus the single root `SKILL.md` exception.

# Open Questions

- None. This plan intentionally makes the canonical command, managed boundary, and scope limits explicit so downstream implementation does not need to reopen the main direction.

# Approval Notes

No canonical tracked plan existed for issue #125 before this artifact. This plan governs only the Windows + `opencode` bootstrap path, designates `precision-squad-bootstrap-skill --project-root .` as the canonical operator entrypoint, and keeps later implementation bounded to a removable `.precision-squad/` deploy surface plus root `SKILL.md`.
