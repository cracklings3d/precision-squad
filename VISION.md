# Vision

## Purpose

`precision-squad` is a specific kind of AI agent harness, built for *long-horizon autonomous software development*. The user states a vision; the system produces working software over days or weeks; the user reviews and gives targeted feedback. The system is the *operator*. The user is the *spec holder* and the *final reviewer*.

## Principle

The vision is the only guideline. The architecture, the instructions, the code — all derive from it. The system is built on *separation of concerns*: each agent has a single concern and a deliberately bounded context, engineered to give it exactly the knowledge it needs to do its job and no more. Agents are not interchangeable; they are specialists.

## Promise

When the user provides a vision, the system breaks it into fragments, executes them in a predictable order, verifies each one against the project's documented contract, and publishes the result. The user comes back to a working project, not a stream of decisions. The user is the *source of soft constraints* the system cannot infer; the system is the *executor* of the work.

## Hard parts

The system must align what it builds with what the user *actually wants*, not just what the user *said*. The user has implicit knowledge — domain-specific soft constraints — that they often forget to convey. The system has two ways to handle this: *inference* and *pulling the user in at well-defined moments*. Both are hard. Inference can fail; pulling the user in too often turns the user back into an operator. The claim to long-horizon autonomy rests on getting this balance right.

## Aspiration

A user with a vision returns a week later to working software that mostly matches their goal, iterates a few times with targeted feedback, and ends up with a project they would have spent months building by hand. The system is honest about what it cannot do. It does not pretend to infer everything. The user is a real participant — not a passive observer — at well-defined moments.