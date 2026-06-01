# Staged Command Surface

Operator reference for the seven-stage command chain that processes issues through review, planning, implementation, and publishing, plus the canonical bootstrap command for new consuming projects.

## Bootstrap Command

### Canonical One-Command Bootstrap

To bootstrap a consuming project with precision-squad skill and config on Windows with opencode:

```powershell
precision-squad-bootstrap-skill --project-root .
```

**Supported environment:** Windows only + opencode. This command is not supported on Linux or macOS.

**What bootstrap validates before writing files:**
- Windows-only execution
- Accessible project root for managed writes
- Usable precision-squad CLI entrypoint
- opencode availability
- GitHub credentials (GITHUB_TOKEN or OpenCode_Github_Token)

**Managed surface (bounded, easy to remove):**
- `./SKILL.md` — project-local skill with commands and rules
- `./.precision-squad/precision-squad.toml` — config defaults for the opencode path
- `./.precision-squad/bootstrap/**` — bootstrap metadata for rerun reporting

**Removal:** To remove all bootstrap state, delete `./SKILL.md` and the `.precision-squad/` directory.

**Idempotency:** Rerunning bootstrap reports per-file outcomes (created/updated/reused/already satisfied) without re-creating unchanged content.

**Blocking conflict:** If `./.precision-squad.toml` exists at the project root, bootstrap stops before writing files, because the root file would shadow the managed `.precision-squad/` boundary.

---

## Stage Chain Overview

```
create issue → review issue → plan → review plan → implement → publish → review impl
```

---

## 1. create issue

**Purpose:** Initiates a fresh run for a new issue.

**Inputs:** None (first stage; no prior artifact required).

**Outputs:**
- `issue-draft.json` — normalized issue artifact containing `title`, `body`, `created_at`

**Gate Behavior:** n/a (first stage; no gate applies).

---

## 2. review issue

**Purpose:** Reviews the issue-draft for actionability, scope, and alignment.

**Inputs:**
- `issue-draft.json`

**Outputs:**
- `issue-review.json` — contains `verdict` field (`approved` | `changes_requested` | `blocked`)

**Gate Behavior:** Stage chain stops if verdict is not `approved`. `plan` is not invoked.

---

## 3. plan

**Purpose:** Produces an approved plan artifact when the issue-review verdict is `approved`.

**Inputs:**
- `issue-review.json`

**Outputs:**
- `approved-plan.json` — produced only when verdict is `approved`
- No artifact produced if verdict is not `approved`

**Gate Behavior:** Stage chain stops if verdict is not `approved`. `review plan` is not invoked.

---

## 4. review plan

**Purpose:** Reviews the approved-plan for soundness and completeness.

**Inputs:**
- `approved-plan.json`

**Outputs:**
- `plan-review.json` — contains `verdict` field (`approved` | `changes_requested` | `blocked`)

**Gate Behavior:** Stage chain stops if verdict is not `approved`. `implement` is not invoked.

---

## 5. implement

**Purpose:** Executes the approved plan and produces repair, QA, and evaluation results.

**Inputs:**
- `approved-plan.json`
- `plan-review.json`

**Outputs:**
- `execution-result.json`
- `repair-result.json`
- `qa-baseline-result.json`
- `qa-result.json`
- `evaluation-result.json`
- `governance-verdict.json`
- `decision-log.attempt-{attempt}.json`

**Gate Behavior:** Governance check after implement. If `governance-verdict.json` does not contain `verdict: approved`, `publish` is not invoked.

---

## 6. publish

**Purpose:** Creates a draft PR when governance verdict is `approved`.

**Inputs:**
- `governance-verdict.json` — must contain `verdict: approved`
- `execution-result.json`
- `repair-result.json`
- `qa-baseline-result.json`
- `qa-result.json`
- `evaluation-result.json`
- `decision-log.attempt-{attempt}.json`

**Outputs:**
- `publish-plan.json`
- `publish-result.json`
- Draft PR in GitHub

**Gate Behavior:** `publish` is invoked only when `governance-verdict.json` contains `verdict: approved`.

---

## 7. review impl

**Purpose:** Final review of the draft PR prior to merge automation.

**Inputs:**
- `approved-plan.json`
- `issue-intake.json`
- `publish-plan.json`
- `publish-result.json` for a published draft PR with URL / PR number metadata

**Outputs:**
- `impl-review.json` — contains `verdict` field (`approved` | `changes_requested` | `blocked`)
- `post-publish-review-result.json` — consumed by GitHub automation

**Gate Behavior:** n/a (final review stage; outcomes handled by GitHub automation).

---

## Artifact Inventory

| Artifact | Stage Produced |
|---|---|
| `issue-draft.json` | create issue |
| `issue-review.json` | review issue |
| `approved-plan.json` | plan |
| `plan-review.json` | review plan |
| `execution-result.json` | implement |
| `governance-verdict.json` | implement |
| `repair-result.json` | implement |
| `qa-baseline-result.json` | implement |
| `qa-result.json` | implement |
| `evaluation-result.json` | implement |
| `decision-log.attempt-{attempt}.json` | implement |
| `publish-plan.json` | publish |
| `publish-result.json` | publish |
| `impl-review.json` | review impl |
| `post-publish-review-result.json` | review impl |

---

## `repair issue` manual retry resume contract

`repair issue --retry-from <run-id> --from "<stage>"` supports exactly these resume targets:

- `review issue`
- `plan`
- `review plan`
- `implement`
- `publish`
- `review impl`

`--from` is valid only with `--retry-from`. It is not supported on standalone stage commands.

### Non-stage context artifacts on resumed retries

Every resumed retry attempt materializes a complete same-run context pack before the selected stage runs:

- `run-request.json` — recreated for the new attempt from the current invocation
- `issue-intake.json` — copied forward from the source attempt
- `issue.md` — regenerated from the preserved intake for the new attempt

Earlier-stage history is preserved by copying only the artifacts before the selected resume point into the new attempt directory. Prior run directories remain unchanged.

### Resume matrix

| Resume target | Required in source run | Preserved into new attempt | Regenerated in new attempt |
|---|---|---|---|
| `review issue` | `issue-draft.json` | `issue-draft.json` | `issue-review.json` and later artifacts |
| `plan` | approved `issue-review.json` | `issue-draft.json`, `issue-review.json` | `approved-plan.json` and later artifacts |
| `review plan` | valid `approved-plan.json` | `issue-draft.json`, `issue-review.json`, `approved-plan.json` | `plan-review.json` and later artifacts |
| `implement` | valid `approved-plan.json`, approved `plan-review.json` | issue/planning artifacts through `plan-review.json` | implement-stage artifacts and later artifacts |
| `publish` | `issue-draft.json`, approved `issue-review.json`, `approved-plan.json`, approved `plan-review.json`, `execution-result.json`, completed `repair-result.json` with `workspace_path`, `qa-baseline-result.json`, `qa-result.json`, `evaluation-result.json`, approved `governance-verdict.json`, `decision-log.attempt-{attempt}.json`, preserved `repair-workspace/repo` | planning + implement artifacts required for publish | `publish-plan.json`, `publish-result.json`, review-impl outputs |
| `review impl` | `approved-plan.json`, `issue-intake.json`, `publish-plan.json`, published-draft-PR `publish-result.json` | earlier artifacts plus publish artifacts | `impl-review.json`, `post-publish-review-result.json` |

`impl-review.json` is produced by `review impl`. It is not an input to `review impl` resume.
