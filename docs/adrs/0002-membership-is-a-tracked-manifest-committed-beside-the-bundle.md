# ADR 0002 — Bundle membership is a tracked text manifest committed beside the bundle

## Status

Accepted

## Context

The bundle object's container could be deserialized to obtain membership, but
that would make basic validation depend on a large changing parser. Unity
already emits a text manifest with exact source paths at build time.

## Decision

Track Unity's own `.manifest` beside the bundle and treat manifest and bundle
as one logical artifact committed together. Validation checks stems against
the manifest, not against a second parser of the container format.

## Consequences

CI gets a stable source of membership, forgotten rebuilds are caught in
review, and the deployable package stays clean because the manifest itself is
not shipped. The cost is a second file that must not drift from the bundle —
accepted, because committing them together and validating references against
the manifest is exactly what keeps the drift impossible to miss.
