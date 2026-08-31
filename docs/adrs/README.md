# ADRs — architecture decision records

An ADR records a decision that **has been made**: the constraint that forced
it, the choice, and what that choice costs. The [RFC](../rfcs/) that may
precede it argues the alternatives; this record is the answer. Neither store
requires the other — a decision can be obvious enough to need no RFC, and an
RFC can be withdrawn without ever producing an ADR.

## What belongs here

- A decision with live alternatives someone will later want to revisit: a
  boundary, an ownership split, a file format, a dependency.
- A decision that constrains future work — the thing a reviewer cites when
  saying "no, we decided that".

What does not belong: an open question (write an [RFC](../rfcs/)), a capability
gap with a proposed closure ([status/improvements.md](../status/improvements.md)),
or an operational failure and its recovery
([a report or runbook](../reports/)).

## Conventions

- Start from [TEMPLATE.md](TEMPLATE.md).
- Files are numbered `NNNN-<short-title>.md`; take the next free number.
- The title is phrased as the **choice made**, not as the question:
  "Synthesize bundles without an editor", not "How do we build without
  Unity?"
- Status is one of `Accepted`, `Superseded`, `Deprecated` — a decision still
  being made is an RFC. One decision per ADR; if a later decision reverses
  this one, mark this file Superseded and link forward rather than editing
  history out of it.
- Consequences must name the honest downside. An ADR that only argues for its
  own decision is useless to whoever is deciding whether to revisit it.
- Where the decision rests on measured engine behaviour, say which artifact or
  tool produced the measurement — the same rule
  [research/research-provenance.md](../research/research-provenance.md)
  enforces for every 7DTD-specific fact.

## Inventory

<!-- inventory:adr:start -->
- [ADR 0007 — The environment-lane runtime helper stays documented-and-per-mod](0007-environment-lane-runtime-helper-documented-per-mod.md) — Accepted
- [ADR 0006 — Render an icon from the mesh with Blender when there is no editor](0006-render-icons-from-the-mesh-with-blender.md) — Accepted
- [ADR 0005 — The editor install is resolved from the game's revision, not pinned](0005-editor-install-is-resolved-not-pinned.md) — Accepted
- [ADR 0004 — One operation registry behind every surface, and no network server](0004-one-operation-registry-and-no-network-server.md) — Accepted
- [ADR 0003 — One bundle per config](0003-one-bundle-per-config.md) — Accepted
- [ADR 0002 — Bundle membership is a tracked text manifest committed beside the bundle](0002-membership-is-a-tracked-manifest-committed-beside-the-bundle.md) — Accepted
- [ADR 0001 — Synthesize bundles without an editor](0001-synthesize-bundles-without-an-editor.md) — Accepted
<!-- inventory:adr:end -->
