# ADR 0007 — The environment-lane runtime helper stays documented-and-per-mod

## Status

Accepted (2026-08-31)

## Context

The environment lane needs a tiny capture/clamp/restore discipline for the
client's global weather/sky/fog statics: snapshot the entry baseline once,
clamp against it (never erase a stronger vanilla storm), and restore the
sentinels (`-1f` force fields, fog alpha `0`, `weatherLightScale 1f`) on both
effect-end and world change. It is documented but unenforced, so every mod that
ships an environment effect re-implements ~20 lines, and the failure is silent
(permanent forced weather, nothing logged).

The proposed closure was a **vendored runtime helper**, like the editor scripts
in `scaffold.PIPELINE_EDITOR_SCRIPTS`.

## Decision

Do **not** ship a runtime C# helper from this repository. Keep the discipline
**documented-and-per-mod**: `docs/authoring/environment-effects.md` carries a
copy-paste reference implementation a mod pastes into its own Harmony assembly,
but the pipeline does not own or vendor game-runtime code.

The deciding facts: the pipeline is a **tool**, not a mod, and the repo's rule
is that general things live here and mod-specific things live in the mod. A
runtime helper runs inside a mod's `Harmony` assembly — closer to mod content
than to tooling. And `make check` can only compile an editor's assemblies, so
the pipeline could not test an editor-independent runtime helper the way it
tests the vendored editor scripts; shipping it would claim a grade it cannot
reach.

## Consequences

- Each environment mod still writes its own ~20 lines, but now from a reference
  implementation in the docs (with the exact engine statics and the sentinels),
  so the discipline is concrete rather than prose.
- The pipeline's identity is unchanged: it ships tooling, not game-runtime code.
- Follow-ups that want stronger enforcement should look at a per-mod test or a
  doc-side contract, not a vendored helper; revisit this ADR only if a runtime
  helper becomes genuinely testable here.
