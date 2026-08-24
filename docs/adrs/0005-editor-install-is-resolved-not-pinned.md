# ADR 0005 — The editor install is resolved from the game's revision, not pinned

## Status

Accepted

## Context

A changeset hardcoded in a script is correct until the game updates its
engine, and then silently wrong — exactly the failure mode this pipeline
exists to make loud.

This decision governs an **opt-in** path. `bundle_source = "synthesized"` is
the default and installs no editor at all, so `install-unity-editor.sh` runs
only for a mod that chose `"unity"`, or for a host that wants
`verify-bundle`/`render-icon`. What is below therefore bounds a cost some hosts
never pay.

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

`shamway unity-release --json` exposes the resolution half on its own, so the
exact URL, changeset and MD5 can be inspected without installing anything —
and the editorless writer stamps the same revision into a bundle it writes,
which is why a host with no editor still needs the revision but never the
download.
