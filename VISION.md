# Vision

## Purpose of the Project

`precision-squad` is a specific kind of AI agent harness, built for *long-horizon autonomous software development*. The user states a vision; the system produces working software over days or weeks; the user reviews and gives targeted feedback. The system is the *operator*. The user is the *spec holder* and the *final reviewer*.

The user is a *solo product designer* — someone who knows the target audience and their requirements well, and who is familiar enough with software architecture to judge design decisions. This is not a tool for non-technical users, and not a tool for developers who want to write the code themselves.

The bet is that *concern separation* between user (vision, constraints, desiderata) and system (execution, decomposition, verification) produces software that is more coherent and homogeneous than the assistant model. A chat assistant helps the user type faster; precision-squad lets the user stop typing and start specifying.

## Project Management

The vision is the only guideline. The architecture, the instructions, the code — all derive from it. The system is built on *separation of concerns*: each agent has a single concern and a deliberately bounded context, engineered to give it exactly the knowledge it needs to do its job and no more. Agents are not interchangeable; they are specialists.

`VISION.md` is the system's *identity*. No agent may edit it without an explicit, audited permit from the user. The permit is granted, scoped, time-limited, and recorded. Enforcement is automatic — at the agent boundary, in CI, and at merge — so the rule cannot drift into a polite suggestion.

The system fails in known ways. It optimizes for executor metrics (tasks done, tests pass) over user metrics (matches goal). It asks the user for every decision and becomes a slow chat. It hides its reasoning in opaque logs. It runs forever without producing results. These are the failure modes the vision names so the system can be designed to defend against them.

The user accepts concrete tradeoffs. Tight control over raw code, token efficiency, certainty of agent convergence, and a precise delivery schedule are *not promised*. The system accepts its own: speed, conversational flexibility, universal reach, and project diversity are also *not promised*. What is promised is coherent, vision-aligned software produced without the user being the operator.

## Envisioned Use

When the user provides a vision, the system breaks it into fragments, executes them in a predictable order, verifies each one against the project's documented contract, and publishes the result. The user comes back to a working project, not a stream of decisions. The user is the *source of soft constraints* the system cannot infer; the system is the *executor* of the work.

The user is engaged in three modes. (1) *Up-front traversal* — at the start of a run, the system and user hold a grill session that walks the decision tree end-to-end, exposing branches and resolving as many as possible. (2) *Cadenced check-in* — every 12 hours, the system surfaces its current state: what was done, what's next, what's blocked. (3) *Ad-hoc escalation* — when the decision tree expands or a new option appears that wasn't traversed up front, the system pauses and asks the user.

## Hard parts

The system must align what it builds with what the user *actually wants*, not just what the user *said*. The user has implicit knowledge — domain-specific soft constraints — that they often forget to convey. The system has two ways to handle this: *inference* and *pulling the user in at well-defined moments*. Both are hard. Inference can fail; pulling the user in too often turns the user back into an operator. The claim to long-horizon autonomy rests on getting this balance right.

*Software entropy* — the tendency for software to drift into inconsistency over time — is exceptionally hard in agentic systems. Each agent may introduce its own conventions, abstractions, or naming. Without active management, the codebase fragments into local dialects that don't compose. The system must enforce coherence across all agents, not just within them.

## Aspiration

A user with a vision returns days or weeks later to working software whose philosophy and functions align with their intent. The system has converged on design decisions consistent with a well-specified vision. The development process — decision logs, handoff contracts, branch rationale — is documented and extractable, so a precision-squad developer can audit and continuously improve the workflow.

Six months in, the vision is succeeding if:

- The vision is reflected in the ADRs (the cascade still works).
- Average execution time after the initial grill exceeds 12 hours (long-horizon autonomy is real).
- Software design decisions converge when the vision is well-specified.
- The end result is functioning software whose philosophy and functions align with the user's intent.
- The development process is documented and extractable for continuous improvement.

The system is honest about what it cannot do. It does not pretend to infer everything. The user is a real participant — not a passive observer — at well-defined moments.
