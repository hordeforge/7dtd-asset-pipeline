# PRDs — product requirement documents

A PRD specifies what a capability should do before it is built: the user or
agent it serves, the behaviour, and what is explicitly out of scope. It
describes intended behaviour; a [report](../reports/README.md) explains observed
behaviour, and an [ADR](../adrs/README.md) records a constraint the design has to
work around.

## Conventions

- Start from [TEMPLATE.md](TEMPLATE.md).
- Files are numbered `NNNN-<short-title>.md`; take the next free number.
- State the consuming surface (`shamway <command>`, an operation name, or a
  gate) and which gates the change must not weaken — see AGENTS.md's gate
  table.
- Out-of-scope is part of the spec, not a footnote.

## Inventory

<!-- inventory:prd:start -->
- [0001 — Contextual model audio review](0001-contextual-model-audio-review.md) —
  implemented 2026-08-25: an explicit, provider-neutral model audition with
  intended-use context and structured advisory criticism
- [0002 — Video-based asset review](0002-video-based-asset-review.md) —
  the same advisory model audition applied to a `7dtd-playtest`-staged clip,
  with the reviewed candidate's generation parameters carried in the evidence
<!-- inventory:prd:end -->
