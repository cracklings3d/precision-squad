# ADR-001: Governance Two-Verdict Model

## Status

Accepted

## Date

2026-05-01

## Context

The original governance model had three verdicts:

- **approved** — QA passed, ready to publish
- **provisional** — baseline was broken, repair improved it but did not fully fix it
- **blocked** — something prevented a successful repair

The `provisional` verdict occupied a middle ground: it meant "better than before, but not green." This created ambiguity about what a provisional verdict actually promised to an operator.

## Decision

Collapse governance to two verdicts: `approved` and `blocked`. Extract the "improved but not green" signal into a separate informational **quality tag** on `ExecutionResult`.

### The Two Verdicts

| Verdict | Meaning |
|---------|---------|
| `approved` | Governance says yes. Creates `draft_pr` automatically. |
| `blocked` | Governance says no. Creates `requires_review` or `follow_up_issue`. Requires human action before publishing. |

### The Quality Tag

| Tag | Meaning |
|-----|---------|
| `green` | Baseline passed, or final matches baseline (no new failures) |
| `improved` | Baseline failed, final has fewer failures (baseline-tolerant repair) |
| `degraded` | New failures introduced by repair |

Quality tags are **informational only**. The verdict (approved/blocked) is what gates publishing.

## Rationale

### Why Remove Provisional

1. **Ambiguous publish semantics.** Provisional verdicts could produce draft PRs, but the PR description had to explain that the fix was incomplete. Operators had to read the fine print to understand what they were approving.

2. **Confused governance contract.** Three verdicts meant three code paths in publishing, three message templates, and three ways for operators to interpret the outcome. Two verdicts simplify the mental model: governance either says yes or no.

3. **Quality is orthogonal to approval.** Whether a repair improved a broken baseline is a useful signal, but it is not a governance decision. A run that improved a broken baseline but introduced new failures is `degraded` and `blocked`. A run that improved a broken baseline without introducing new failures is `improved` and may be `approved` if the baseline was already failing.

4. **Provisional conflated two concerns.** It tried to express both "the baseline was broken" and "the repair helped." These are now separate: the quality tag captures "the repair helped" and the verdict captures "is this ready to publish."

### Why a Quality Tag Instead of a Verdict

1. **Informational, not gating.** The quality tag does not control publishing. It provides context for the operator to understand what happened during the run.

2. **Composable with verdicts.** Any quality tag can appear with either verdict. This is more expressive than a three-verdict model where provisional was a special case.

3. **Simpler governance logic.** `apply_governance` returns `approved` or `blocked`. No special-case handling for "improved but not green."

## Trade-offs

### What We Lost

- **Explicit provisional publish path.** The old model had a dedicated code path for provisional → draft PR with caveats. Now, an `improved` quality tag with `approved` verdict achieves the same outcome, but the publishing code does not distinguish it from a `green` + `approved` run. If we need provisional-specific publish behavior in the future, we will need to add it back.

- **Quality-aware publish descriptions.** The publish plan body no longer has a dedicated "Provisional Summary" section. Operators must check the quality tag in the execution result to understand the baseline context.

### What We Gained

- **Simpler governance contract.** Two outcomes, clear semantics.
- **Better separation of concerns.** Quality is a measurement; approval is a decision.
- **Fewer code paths.** Publishing, CLI output, and integration tests all have one fewer branch to handle.
- **Extensibility.** New quality tags (e.g., `unchanged`, `partially_improved`) can be added without changing the governance model.

## Consequences

- All references to `provisional` as a governance verdict must be removed from the codebase.
- `ExecutionResult.quality` replaces the provisional signal.
- Integration tests verify quality tags separately from verdicts.
- The publish plan body uses the quality tag for context but does not gate on it.

## References

- [CONTEXT.md](../../CONTEXT.md) — Governance Verdicts, Quality Tag
- [Implementation Plan](../implementation-plan.md) — Phase 1
- [architecture.md](../architecture.md) — Governance section (updated)
