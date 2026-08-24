# ADR 0005 — The editor install is resolved from the game's revision, not pinned

## Status

Accepted

## Context

A changeset hardcoded in a script is correct until the game updates its
engine, and then silently wrong — exactly the failure mode this pipeline
exists to make loud.

## Decision

`unity_release.py` asks Unity's official release service for the changeset,
archive URL, and MD5 belonging to whatever revision the project needs, and the
installer refuses any download Unity published no checksum for. The version
itself still comes from the installed game.

## Consequences

The chain is game bundle → revision → official download → verified bytes, and
the installer stays usable across game updates without editing a pin. The cost
is install-time dependence on Unity's release service being reachable and
honest; the MD5 check is what bounds that trust.
