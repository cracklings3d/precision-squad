# Staged Command Surface

Operator reference for the seven-stage command chain that processes issues through review, planning, implementation, and publishing.

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
- `issue-review.json` — contains `verdict` field (`approved` | `blocked`)

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
- `plan-review.json` — contains `verdict` field (`approved` | `blocked`)

**Gate Behavior:** Stage chain stops if verdict is not `approved`. `implement` is not invoked.

---

## 5. implement

**Purpose:** Executes the approved plan and produces repair, QA, and evaluation results.

**Inputs:**
- `approved-plan.json`
- `plan-review.json`

**Outputs:**
- `impl-review.json`
- `repair-result.json`
- `qa-result.json`
- `evaluation-result.json`
- `governance-verdict.json`

**Gate Behavior:** Governance check after implement. If `governance-verdict.json` does not contain `verdict: approved`, `publish` is not invoked.

---

## 6. publish

**Purpose:** Creates a draft PR when governance verdict is `approved`.

**Inputs:**
- `governance-verdict.json` — must contain `verdict: approved`
- Implementation artifacts from `implement`

**Outputs:**
- `publish-plan.json`
- `publish-result.json`
- Draft PR in GitHub

**Gate Behavior:** `publish` is invoked only when `governance-verdict.json` contains `verdict: approved`.

---

## 7. review impl

**Purpose:** Final review of the draft PR prior to merge automation.

**Inputs:**
- Draft PR URL/number and head SHA
- `impl-review.json`

**Outputs:**
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
| `impl-review.json` | implement |
| `governance-verdict.json` | implement |
| `repair-result.json` | implement |
| `qa-result.json` | implement |
| `evaluation-result.json` | implement |
| `publish-plan.json` | publish |
| `publish-result.json` | publish |
| `post-publish-review-result.json` | review impl |
