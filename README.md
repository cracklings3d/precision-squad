# precision-squad

`precision-squad` is a docs-first workflow control system for issue repair.

It keeps product logic in this repository and treats repository documentation as the execution contract:

- GitHub issue intake
- run planning and repair control
- machine-readable artifact persistence
- governance and merge gating
- PR and issue publishing

## Status

This repository is in bootstrap.

The current near-term milestones are:

1. bootstrap the Python package, tooling, CI, and issue/PR workflow assets
2. implement GitHub PAT-backed issue intake
3. add the local run store
4. define the executor seam and documented local contract extraction
5. build the first end-to-end CLI flow
6. add governance v1 and publishing v1

## Product Boundary

- repository docs provide the local setup and QA contract
- optional repair agents consume the extracted contract artifacts
- `precision-squad` owns workflow control.
- `precision-squad` is not another prompt bundle or role-loop runtime.

## MVP Shape

The first MVP should prove one control loop:

1. accept a GitHub issue
2. normalize it into a runnable request
3. extract the documented local setup and QA contract
4. execute the repair workflow
5. collect artifacts and evidence
6. apply governance
7. publish a draft PR or a blocked verdict

## V1 Operating Assumptions

- CLI/service first
- PAT-only GitHub authentication
- filesystem-backed run persistence
- docs-first execution wrapped behind a narrow adapter boundary

## Non-Goals For V1

- GitHub App authentication
- MCP or remote runner support
- deep repo-specific inference machinery
- database-backed persistence
- multi-tenant or broad parallel execution

## Development

Install the project and development tools:

```bash
python -m pip install -e ".[dev]"
```

Run the local checks:

```bash
ruff check .
pyright
pytest
```

## CLI

Primary repair command:

```bash
python -m precision_squad.cli repair issue owner/repo#number --repo-path <local-repo>
```

Optional project config:

- locations, in search order: `./.precision-squad.toml` and `./.precision-squad/precision-squad.toml`
- precedence: CLI flags override config values
- boolean overrides: use `--publish` / `--no-publish` and `--force` / `--no-force`
- schema: command-shaped TOML tables only; top-level scalar keys are invalid
- discovery root:
  - `repair issue`: `--repo-path` when provided, otherwise the current working directory
  - `publish run`: the current working directory
  - `install-skill`: `--project-root` when provided, otherwise the current working directory
- relative path values from config are resolved relative to the config file that supplied them

Example:

```toml
[repair.issue]
repo_path = "."
runs_dir = ".precision-squad/runs"
repair_agent = "opencode"
publish = false
repair_model = "model-name"
review_model = "model-name"
approved_plan_path = "approved-plan.json"

[publish.run]
runs_dir = ".precision-squad/runs"
review_model = "model-name"

[install-skill]
project_root = "."
force = false
```

Supported keys for `repair issue`:

- `repo_path`
- `runs_dir`
- `publish`
- `repair_agent`
- `repair_model`
- `review_model`
- `approved_plan_path`

Supported keys for `publish run`:

- `runs_dir`
- `review_model`

Supported keys for `install-skill`:

- `project_root`
- `force`

CLI-only for this feature:

- positional arguments such as `issue_ref` and `run_id`
- command and subcommand names
- `retry_from`, because run selection remains an explicit invocation-scoped operator choice

Legacy alias still supported:

```bash
python -m precision_squad.cli run issue owner/repo#number --repo-path <local-repo>
```

Publish an approved or provisional stored run without rerunning repair:

```bash
python -m precision_squad.cli publish run <run-id>
```

Install a project-local `SKILL.md` into the current repository:

```bash
python -m precision_squad.cli install-skill --project-root .
```

Interactive bootstrap for consuming projects:

```bash
precision-squad-bootstrap-skill --project-root .
```

The bootstrap script explains what it will do and asks for confirmation before writing anything.

This is the recommended way to bootstrap agent guidance into a consuming project. Do not rely on hidden dependency-install hooks for this.

If you use the `skills` ecosystem directly, this repo also exposes a skill package under `skills/precision-squad/` so a project can install it with `npx skills add <repo> ...`.

## Key Documents

- `docs/architecture.md` - current docs-first architecture
- `docs/operator-skill.md` - practical operator/agent workflow guide for GitHub + precision-squad
- `docs/archive/architecture-v1.md` - archived bootstrap architecture for historical reference
- `docs/archive/PRECISION_SQUAD_HANDOFF.md` - archived handoff from the earlier `orchestrator` exploration

## Issue Workflow

This repository follows an issue-first GitHub workflow:

1. define work in a GitHub issue
2. implement it through a linked PR
3. keep the PR scoped to the issue

PRs should include a closing reference such as `Closes #123`.
