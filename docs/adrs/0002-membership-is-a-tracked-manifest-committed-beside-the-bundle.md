# ADR 0002 — Bundle membership is a tracked text manifest committed beside the bundle

## Status

Accepted (2026-08-24)

## Context

The bundle object's container could be deserialized to obtain membership, but
that would make basic validation depend on a large changing parser. Unity
already emits a text manifest with exact source paths at build time.

## Decision

Track Unity's own `.manifest` beside the bundle and treat manifest and bundle
as one logical artifact committed together. Validation checks stems against
the manifest, not against a second parser of the container format.

**Correction, 2026-08-25 — who writes it.** This record was written when an
editor built every bundle, so Unity was always the manifest's author. With
`bundle_source = "synthesized"` now the default
([ADR 0001](0001-synthesize-bundles-without-an-editor.md)), the writer emits
the manifest itself from its own membership record, and Unity's file is staged
only for a bundle an editor built (`build.py`). The decision is unchanged: one
tracked text manifest beside the bundle, committed with it, validated against
it rather than re-parsing the container.

## Consequences

CI gets a stable source of membership, forgotten rebuilds are caught in
review, and the deployable package stays clean because the manifest itself is
not shipped. The cost is a second file that must not drift from the bundle —
accepted, because committing them together and validating references against
the manifest is exactly what keeps the drift impossible to miss.
