# PRD — <capability>

## Status

Draft / In progress / Implemented. Name the modules that are the source of
truth and the surfaces that expose it (`shamway <command>`, an operation in
`operations.OPERATIONS`, a generator, a gate). If part of this page is already
stale, say so here rather than leaving a reader to discover it in Design.

## Problem

What is impossible or unsafe without this, stated from the situation rather
than from the solution. Include the real constraints that shape it: no network,
no writes into a game install, Unity optional, an adopting mod may not check
this repository out.

## Goals

Numbered and verifiable; each one matches a box under Acceptance.

## Non-goals

What this deliberately does not do, and why the omission is a feature. This is
what stops the next session from "fixing" it.

## Design

The mechanism, in the fewest sections that carry its real shape. State why each
non-obvious choice was made. Where the code holds a table (operations,
generators, capabilities, doc topics), mirror it exactly and treat a mismatch
as a bug in this page.

**Gates.** Which gates in AGENTS.md this must not weaken, and which new gate it
adds. A capability that produces an artifact says what its evidence is worth
and which gates cannot run without an editor or an installed game.

**Registries.** Every table the change must be added to, by name —
`operations.OPERATIONS` and `api._DISPATCH`, `generators.GENERATORS`,
`docs.TOPICS`, `scripts.SCRIPTS`, `prompts.KINDS`, `capabilities.REGISTRY`,
`scaffold.PIPELINE_EDITOR_SCRIPTS`.

**Implementation.** Numbered phases with concrete file paths, each
independently checkable.

## Failure modes

A table of condition → behaviour, covering every "what happens when X is
missing" a caller would otherwise read the source to answer.

## Acceptance criteria

Checkboxes, each traceable to a goal. Use `[ ]` honestly; an unchecked box that
names the gap beats a checked box that is aspirational. Offline gates are never
the last box: acceptance ends with a fresh client and a human look or listen.

## Open questions

Real unresolved decisions. A known bug belongs in Design or a
[report](../reports/), not here.
